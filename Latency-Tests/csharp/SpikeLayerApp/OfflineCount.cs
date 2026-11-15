// SpikeLayerApp.exe --count sessions/NAME [--grid]
//
// Re-counts spikes in a SAVED session with exactly the same code the live
// server uses (SpikeCounter.CountChannel), and writes
// sessions/NAME_counts_csharp.csv: one row per window, 60 counts + 60 noise
// levels (sigma, uV). compare_counts.py then counts the same file in Python
// and checks the two agree. This is a test of the C# counter; it never runs
// during a live session.
//
// Which windows:
//   - a --serve session (its .json lists windows): those windows, with the same
//     pulse masks as live
//   - a --save recording, or --grid: back-to-back 100 ms windows, no masks.
//     A window is skipped if its 10 ms margins would run off either end of the file.
//
// Nothing here touches McsUsbNet.dll.

using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;

static class OfflineCount
{
    public const int GRID_MS = 100;

    class Win { public uint Id; public long First; public int N; public Piece[] Left, Right; }

    public static int Run(string session, bool grid)
    {
        string prefix = session;
        if (prefix.EndsWith(".json") || prefix.EndsWith(".bin")) prefix = prefix.Substring(0, prefix.LastIndexOf('.'));
        string json = File.ReadAllText(prefix + ".json");
        var inv = CultureInfo.InvariantCulture;

        int fs = (int)Num(json, "fs");
        int streams = (int)Num(json, "n_streams");
        double uv = Num(json, "uv_per_count");
        if (streams != Recording.CHANNELS)
            throw new NotSupportedException("expected " + Recording.CHANNELS + " streams, file has " + streams);

        long total = new FileInfo(prefix + ".bin").Length / (4L * streams);
        int margin = fs * SpikeCounter.MARGIN_MS / 1000;
        int refractory = fs * SpikeCounter.REFRACTORY_MS / 1000;

        var windows = grid ? new List<Win>() : SessionWindows(json);
        string source = "session windows (with pulse masks)";
        if (windows.Count == 0)
        {
            source = GRID_MS + " ms grid (no masks)";
            int n = fs * GRID_MS / 1000;
            for (long s = 0; s + n <= total; s += n)
                windows.Add(new Win { Id = (uint)(s / n), First = s, N = n, Left = new Piece[0], Right = new Piece[0] });
        }

        string outPath = prefix + "_counts_csharp.csv";
        int done = 0, skipped = 0;
        using (var bin = new FileStream(prefix + ".bin", FileMode.Open, FileAccess.Read, FileShare.Read))
        using (var w = new StreamWriter(outPath, false, new UTF8Encoding(false)))
        {
            var head = new StringBuilder("window,first_sample,n_samples");
            for (int c = 0; c < streams; c++) head.Append(",count_").Append(c);
            for (int c = 0; c < streams; c++) head.Append(",noise_uv_").Append(c);
            w.WriteLine(head);

            foreach (var win in windows)
            {
                if (win.N <= 0 || win.First - margin < 0 || win.First + win.N + margin > total) { skipped++; continue; }

                int len = win.N + 2 * margin;
                var raw = new byte[(long)len * streams * 4];
                bin.Position = (win.First - margin) * streams * 4L;
                ReadExactly(bin, raw);
                var ints = new int[len * streams];
                Buffer.BlockCopy(raw, 0, ints, 0, raw.Length);

                var mask = WaveRules.SpikeMask(win.Left, win.Right, win.N, fs, SpikeCounter.MASK_AFTER_US);
                var counts = new int[streams];
                var noise = new double[streams];
                var x = new double[len];
                for (int c = 0; c < streams; c++)
                {
                    for (int k = 0; k < len; k++) x[k] = ints[k * streams + c] * uv;
                    counts[c] = SpikeCounter.CountChannel(x, margin, win.N, mask, refractory, out noise[c]);
                }

                var row = new StringBuilder();
                row.Append(win.Id).Append(',').Append(win.First).Append(',').Append(win.N);
                foreach (int v in counts) row.Append(',').Append(v);
                foreach (double v in noise) row.Append(',').Append(v.ToString("R", inv));
                w.WriteLine(row);
                done++;
            }
        }

        Console.WriteLine("  {0}: {1} windows counted, {2} skipped (no room for the 10 ms margins)", source, done, skipped);
        Console.WriteLine("  wrote " + outPath);
        Console.WriteLine("  compare:  python compare_counts.py " + prefix);
        return done > 0 ? 0 : 1;
    }

    // Windows logged by the server: one line each in the .json (see Recording.LogWindow).
    static List<Win> SessionWindows(string json)
    {
        var list = new List<Win>();
        var line = new Regex("\"window\": (\\d+), \"first_sample\": (-?\\d+), \"n_samples\": (\\d+), \"left\": (.*?), \"right\": (.*?), \"counts\"");
        foreach (Match m in line.Matches(json))
            list.Add(new Win
            {
                Id = uint.Parse(m.Groups[1].Value),
                First = long.Parse(m.Groups[2].Value),
                N = int.Parse(m.Groups[3].Value),
                Left = Pieces(m.Groups[4].Value),
                Right = Pieces(m.Groups[5].Value),
            });
        return list;
    }

    static Piece[] Pieces(string s)
    {
        var list = new List<Piece>();
        foreach (Match m in Regex.Matches(s, "\\[(-?\\d+), (\\d+)\\]"))
            list.Add(new Piece { AmplitudeUv = int.Parse(m.Groups[1].Value), LengthUs = uint.Parse(m.Groups[2].Value) });
        return list.ToArray();
    }

    static double Num(string json, string key)
    {
        var m = Regex.Match(json, "\"" + key + "\": (-?[0-9.eE+-]+)");
        if (!m.Success) throw new InvalidDataException("no \"" + key + "\" in the .json");
        return double.Parse(m.Groups[1].Value, CultureInfo.InvariantCulture);
    }

    static void ReadExactly(Stream s, byte[] buf)
    {
        int got = 0;
        while (got < buf.Length)
        {
            int r = s.Read(buf, got, buf.Length - got);
            if (r <= 0) throw new EndOfStreamException();
            got += r;
        }
    }
}
