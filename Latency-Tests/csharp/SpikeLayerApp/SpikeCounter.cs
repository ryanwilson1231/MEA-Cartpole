// Counts spikes per channel in one window. Same method as count_spikes() in
// Baseline-Protocol/Hardware/mea_device.py, plus three fixes from
// Round-1-Tasks/T5-spike-detection.md:
//   - margins: filter 10 ms extra on each side and count only the middle,
//     so the filter's start-up swing isn't counted (T5 fix 1)
//   - 1 ms refractory period, so one spike isn't counted twice (T5 fix 2)
//   - pulse mask: ignore crossings from each pulse's start until 2 ms after it (T5 fix 4)
//
// Steps per channel:
//   0. bridge each masked stretch with a straight line, so the artifact never
//      reaches the filter (see BridgeMasked)
//   1. band-pass 300-3000 Hz, forwards then backwards (zero phase, like sosfiltfilt)
//   2. noise = median(|filtered|) / 0.6745, over the unmasked middle samples
//   3. count downward crossings of -5 x noise
//
// Nothing here touches McsUsbNet.dll.

using System;
using System.Threading.Tasks;

static class SpikeCounter
{
    public const double THRESHOLD_SD  = 5.0;
    public const int    MARGIN_MS     = 10;
    public const int    REFRACTORY_MS = 1;
    public const int    MASK_AFTER_US = 2000;   // tune after the saline run

    // scipy.signal.butter(2, [300, 3000], btype="bandpass", fs=50000, output="sos")
    static readonly double[][] SOS_50K =
    {
        new[] { 0.02307442171693457, 0.04614884343386914, 0.02307442171693457, 1.0, -1.5526244517732186, 0.6512722944212291 },
        new[] { 1.0, -2.0, 1.0, 1.0, -1.9487924351826795, 0.9504301927924739 },
    };

    // Count spikes on every channel for the window [start, start + n) in absolute frames.
    // Returns null if the data (including margins) isn't in memory.
    public static int[] CountWindow(Recording rec, long start, int n, bool[] mask)
    {
        if (rec.SampleRate != 50000) throw new NotSupportedException("filter coefficients are for 50 kHz");
        int margin = rec.SampleRate * MARGIN_MS / 1000;
        int refractory = rec.SampleRate * REFRACTORY_MS / 1000;
        var counts = new int[Recording.CHANNELS];
        bool missing = false;

        Parallel.For(0, Recording.CHANNELS, ch =>
        {
            var x = new double[n + 2 * margin];
            if (!rec.CopyUv(ch, start - margin, x.Length, x)) { missing = true; return; }
            counts[ch] = CountChannel(x, margin, n, mask, refractory);
        });
        return missing ? null : counts;
    }

    // x = window with `margin` extra samples on each side.
    public static int CountChannel(double[] x, int margin, int n, bool[] mask, int refractory)
    {
        BridgeMasked(x, margin, n, mask);

        // Remove the offset first so the filter doesn't start with a big step.
        double mean = 0;
        for (int i = 0; i < x.Length; i++) mean += x[i];
        mean /= x.Length;
        var y = new double[x.Length];
        for (int i = 0; i < x.Length; i++) y[i] = x[i] - mean;

        FiltFilt(y);

        // noise from the unmasked middle
        var abs = new double[n];
        int m = 0;
        for (int k = 0; k < n; k++) if (!mask[k]) abs[m++] = Math.Abs(y[margin + k]);
        if (m == 0) return 0;
        double noise = Median(abs, m) / 0.6745;
        if (noise <= 0) return 0;
        double thr = -THRESHOLD_SD * noise;

        int count = 0;
        int last = int.MinValue / 2;
        bool prevBelow = y[margin - 1] < thr;
        for (int k = 0; k < n; k++)
        {
            bool below = y[margin + k] < thr;
            if (below && !prevBelow && !mask[k] && k - last >= refractory) { count++; last = k; }
            prevBelow = below;
        }
        return count;
    }

    // Replace each masked stretch with a straight line between the samples on
    // either side, before filtering. The filter runs forwards and backwards, so
    // without this an artifact's ringing spreads up to ~4 ms BEFORE the pulse,
    // where the mask doesn't reach: on fake data, every pulse added 2-3 false
    // spikes on every channel.
    static void BridgeMasked(double[] x, int margin, int n, bool[] mask)
    {
        int k = 0;
        while (k < n)
        {
            if (!mask[k]) { k++; continue; }
            int end = k;
            while (end < n && mask[end]) end++;
            // x[margin + k - 1] and x[margin + end] always exist thanks to the margins
            double a = x[margin + k - 1], b = x[margin + end];
            int len = end - k + 1;
            for (int j = k; j < end; j++) x[margin + j] = a + (b - a) * (j - k + 1) / len;
            k = end;
        }
    }

    static void FiltFilt(double[] y)
    {
        foreach (var s in SOS_50K) Biquad(y, s, false);
        foreach (var s in SOS_50K) Biquad(y, s, true);
    }

    // Direct form II transposed, one second-order section, in place.
    static void Biquad(double[] y, double[] s, bool backwards)
    {
        double b0 = s[0], b1 = s[1], b2 = s[2], a1 = s[4], a2 = s[5];
        double z1 = 0, z2 = 0;
        int n = y.Length;
        for (int j = 0; j < n; j++)
        {
            int i = backwards ? n - 1 - j : j;
            double xin = y[i];
            double o = b0 * xin + z1;
            z1 = b1 * xin - a1 * o + z2;
            z2 = b2 * xin - a2 * o;
            y[i] = o;
        }
    }

    // Median of the first `m` values (reorders them). Quickselect, O(m).
    static double Median(double[] a, int m)
    {
        int mid = m / 2;
        double hi = Select(a, 0, m - 1, mid);
        if (m % 2 == 1) return hi;
        double lo = double.NegativeInfinity;
        for (int i = 0; i < mid; i++) if (a[i] > lo) lo = a[i];
        return (lo + hi) / 2;
    }

    static double Select(double[] a, int left, int right, int k)
    {
        var rnd = new Random(12345);
        while (left < right)
        {
            double pivot = a[rnd.Next(left, right + 1)];
            int i = left, j = right;
            while (i <= j)
            {
                while (a[i] < pivot) i++;
                while (a[j] > pivot) j--;
                if (i <= j) { double t = a[i]; a[i] = a[j]; a[j] = t; i++; j--; }
            }
            if (k <= j) right = j;
            else if (k >= i) left = i;
            else return a[k];
        }
        return a[k];
    }
}
