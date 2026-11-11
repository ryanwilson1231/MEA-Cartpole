// Holds the last few seconds of every channel in memory (for spike counting),
// and, while a session is open, writes everything to sessions/<name>.bin + .json.
//
// .bin layout: raw AD counts, int32 little-endian, frame-major:
//   sample 0 ch 0..59, sample 1 ch 0..59, ...
// Multiply by uv_per_digit from the .json to get microvolts.
//
// Nothing here touches McsUsbNet.dll.

using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using System.Threading;

class Recording
{
    public const int CHANNELS = 60;

    public readonly int SampleRate;
    public readonly int Capacity;               // frames kept in memory per channel
    readonly double uvPerDigit;
    readonly bool   uvIsFallback;

    readonly int[][] ring = new int[CHANNELS][];
    long total;                                 // frames received since recording started
    readonly object sync = new object();

    // open session (all guarded by `sync`)
    string sessionName, binPath, jsonPath;
    long   sessionStart;
    DateTime sessionStarted;
    BlockingCollection<byte[]> writeQueue;
    Thread writer;
    FileStream file;
    readonly List<string> windowLog = new List<string>();

    public Recording(int sampleRate, int seconds, double uvPerDigit, bool uvIsFallback)
    {
        if (!BitConverter.IsLittleEndian) throw new PlatformNotSupportedException("the .bin format assumes little-endian");
        SampleRate = sampleRate;
        Capacity = sampleRate * seconds;
        this.uvPerDigit = uvPerDigit;
        this.uvIsFallback = uvIsFallback;
        for (int ch = 0; ch < CHANNELS; ch++) ring[ch] = new int[Capacity];
    }

    public long Total { get { lock (sync) return total; } }
    public bool SessionOpen { get { lock (sync) return file != null; } }

    // ---------------------------------------------------------- data in

    // Called from the DLL's callback thread with `n` new frames per channel.
    public void Append(int[][] channels, int n)
    {
        if (n <= 0) return;
        lock (sync)
        {
            int pos = (int)(total % Capacity);
            int first = Math.Min(n, Capacity - pos);
            for (int ch = 0; ch < CHANNELS; ch++)
            {
                Array.Copy(channels[ch], 0, ring[ch], pos, first);
                if (first < n) Array.Copy(channels[ch], first, ring[ch], 0, n - first);
            }

            if (file != null)
            {
                var interleaved = new int[n * CHANNELS];
                for (int k = 0, j = 0; k < n; k++)
                    for (int ch = 0; ch < CHANNELS; ch++, j++) interleaved[j] = channels[ch][k];
                var bytes = new byte[interleaved.Length * 4];
                Buffer.BlockCopy(interleaved, 0, bytes, 0, bytes.Length);
                writeQueue.Add(bytes);          // disk writes happen on the writer thread
            }

            total += n;
            Monitor.PulseAll(sync);
        }
    }

    // Wait until frame `absFrame` has arrived. False on timeout.
    public bool WaitFor(long absFrame, int timeoutMs)
    {
        var deadline = DateTime.UtcNow.AddMilliseconds(timeoutMs);
        lock (sync)
        {
            while (total < absFrame)
            {
                int left = (int)(deadline - DateTime.UtcNow).TotalMilliseconds;
                if (left <= 0 || !Monitor.Wait(sync, left)) { if (total < absFrame) return false; }
            }
            return true;
        }
    }

    // Copy `len` frames of one channel starting at absolute frame `start`, in uV.
    // False if those frames aren't in memory (not arrived yet, or overwritten).
    public bool CopyUv(int ch, long start, int len, double[] dest)
    {
        lock (sync)
        {
            if (start < 0 || start + len > total || start < total - Capacity) return false;
            var src = ring[ch];
            for (int k = 0; k < len; k++) dest[k] = src[(int)((start + k) % Capacity)] * uvPerDigit;
            return true;
        }
    }

    // ---------------------------------------------------------- sessions

    // Returns null on success, otherwise why the session couldn't start.
    public string StartSession(string name, string directory)
    {
        string bad = CheckName(name);
        if (bad != null) return bad;
        Directory.CreateDirectory(directory);
        string bin = Path.Combine(directory, name + ".bin");
        string json = Path.Combine(directory, name + ".json");
        if (File.Exists(bin) || File.Exists(json))
            return "session '" + name + "' already exists in " + directory + "; refusing to overwrite it";

        EndSession();
        var fs = new FileStream(bin, FileMode.CreateNew, FileAccess.Write, FileShare.Read, 1 << 20);
        var queue = new BlockingCollection<byte[]>();
        var t = new Thread(() =>
        {
            foreach (var chunk in queue.GetConsumingEnumerable()) fs.Write(chunk, 0, chunk.Length);
            fs.Flush();
        });
        t.IsBackground = true;
        t.Name = "session writer";

        lock (sync)
        {
            sessionName = name; binPath = bin; jsonPath = json;
            sessionStart = total;
            sessionStarted = DateTime.Now;
            windowLog.Clear();
            file = fs; writeQueue = queue; writer = t;
            t.Start();
            WriteJson(false);
        }
        return null;
    }

    // Absolute frame -> sample index in the session's .bin file.
    public long SessionSample(long absFrame) { lock (sync) return absFrame - sessionStart; }

    public void LogWindow(uint window, long firstSample, int nSamples, Piece[] left, Piece[] right, int[] counts)
    {
        var sb = new StringBuilder();
        sb.AppendFormat(CultureInfo.InvariantCulture,
                        "{{\"window\": {0}, \"first_sample\": {1}, \"n_samples\": {2}, \"left\": {3}, \"right\": {4}, \"counts\": [{5}]}}",
                        window, firstSample, nSamples, PiecesJson(left), PiecesJson(right), string.Join(", ", counts));
        lock (sync) windowLog.Add(sb.ToString());
    }

    public void EndSession()
    {
        FileStream fs; BlockingCollection<byte[]> queue; Thread t;
        lock (sync)
        {
            if (file == null) return;
            fs = file; queue = writeQueue; t = writer;
            file = null;                 // Append stops queueing from here on
            queue.CompleteAdding();
        }
        t.Join();                        // drain what's left to disk
        fs.Dispose();
        lock (sync) WriteJson(true);
        Console.WriteLine("  Session '{0}' closed: {1}", sessionName, binPath);
    }

    // ---------------------------------------------------------- helpers

    void WriteJson(bool finished)
    {
        long samples = new FileInfo(binPath).Exists && finished
                       ? new FileInfo(binPath).Length / (4 * CHANNELS) : -1;
        var inv = CultureInfo.InvariantCulture;
        var sb = new StringBuilder();
        sb.Append("{\n");
        sb.AppendFormat(inv, "  \"name\": \"{0}\",\n", Escape(sessionName));
        sb.AppendFormat(inv, "  \"started\": \"{0:yyyy-MM-ddTHH:mm:ss.fffzzz}\",\n", sessionStarted);
        if (finished) sb.AppendFormat(inv, "  \"ended\": \"{0:yyyy-MM-ddTHH:mm:ss.fffzzz}\",\n", DateTime.Now);
        sb.AppendFormat(inv, "  \"complete\": {0},\n", finished ? "true" : "false");
        sb.AppendFormat(inv, "  \"bin_file\": \"{0}\",\n", Escape(Path.GetFileName(binPath)));
        sb.Append("  \"dtype\": \"int32\",\n");
        sb.Append("  \"byte_order\": \"little\",\n");
        sb.Append("  \"layout\": \"frame-major: for each sample, channels 0..59\",\n");
        sb.AppendFormat(inv, "  \"n_channels\": {0},\n", CHANNELS);
        sb.AppendFormat(inv, "  \"sample_rate_hz\": {0},\n", SampleRate);
        sb.AppendFormat(inv, "  \"uv_per_digit\": {0:R},\n", uvPerDigit);
        sb.AppendFormat(inv, "  \"uv_per_digit_is_fallback\": {0},\n", uvIsFallback ? "true" : "false");
        if (finished) sb.AppendFormat(inv, "  \"n_samples\": {0},\n", samples);
        sb.Append("  \"windows\": [");
        for (int i = 0; i < windowLog.Count; i++) sb.Append(i == 0 ? "\n    " : ",\n    ").Append(windowLog[i]);
        sb.Append(windowLog.Count > 0 ? "\n  ]\n}\n" : "]\n}\n");
        File.WriteAllText(jsonPath, sb.ToString(), new UTF8Encoding(false));
    }

    static string PiecesJson(Piece[] wave)
    {
        var parts = new string[wave.Length];
        for (int i = 0; i < wave.Length; i++) parts[i] = "[" + wave[i].AmplitudeUv + ", " + wave[i].LengthUs + "]";
        return "[" + string.Join(", ", parts) + "]";
    }

    static string CheckName(string name)
    {
        if (string.IsNullOrEmpty(name)) return "session name is empty";
        if (name.Length > 100) return "session name is longer than 100 characters";
        if (name[0] == '.') return "session name can't start with '.'";
        foreach (char c in name)
            if (!(char.IsLetterOrDigit(c) || c == '_' || c == '-' || c == '.'))
                return "session name '" + name + "' has '" + c + "'; use letters, digits, _ - . only";
        return null;
    }

    static string Escape(string s) { return (s ?? "").Replace("\\", "\\\\").Replace("\"", "\\\""); }
}
