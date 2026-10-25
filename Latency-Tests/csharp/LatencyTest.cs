// Branch B - native C# path.
//
// Same measurements as the pythonnet branch, but calling McsUsbNet.dll directly
// with no Python in the loop. If this is much faster, the pythonnet boundary is
// the bottleneck and a native layer is worth building.
//
//   build.bat
//   LatencyTest.exe              record-only timing
//   LatencyTest.exe --stim       + round-trip latency   (SALINE ONLY)
//
// Writes latency_csharp.csv next to the executable.

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Threading;
using Mcs.Usb;

class LatencyTest
{
    const int SAMPLERATE   = 50000;
    const int NUM_CHANNELS = 60;
    const int QUEUE_SIZE   = SAMPLERATE;        // 1 s ring buffer per channel
    const int THRESHOLD    = SAMPLERATE / 10;   // callback every 100 ms
    const double ARTIFACT_SIGMA = 8.0;

    static readonly int[] WatchChannels = { 0, 1, 30, 31 };

    static CMeaUSBDeviceNet dacq;
    static int channelsInBlock;

    // timing state, written from the DLL's callback thread
    static readonly List<double> callbackDurations = new List<double>();
    static readonly List<double> callbackTimes     = new List<double>();
    static readonly List<int>    frameCounts       = new List<int>();
    static int[,] dataBuffer = new int[NUM_CHANNELS, 2500];

    // recent frames on the watched channels, for artifact search
    class Snapshot { public double T; public Dictionary<int,int[]> Watch; }
    static readonly Queue<Snapshot> recent = new Queue<Snapshot>();
    static readonly object recentLock = new object();

    static readonly Stopwatch clock = Stopwatch.StartNew();
    static double Now() { return clock.Elapsed.TotalMilliseconds; }

    // ------------------------------------------------------------------ main

    static int Main(string[] args)
    {
        bool doStim    = args.Contains("--stim");
        int  stimSteps = ArgInt(args, "--stim-steps", 100);
        int  seconds   = ArgInt(args, "--seconds", 10);

        var results = new Dictionary<string, double>();

        Console.WriteLine(new string('=', 70));
        Console.WriteLine("BRANCH B - native C# path");
        Console.WriteLine(new string('=', 70));

        if (!Connect()) return 1;

        try
        {
            PhaseRecord(seconds, results);
            if (doStim) PhaseRoundTrip(stimSteps, results);
        }
        finally
        {
            try { dacq.StopDacq(0); } catch { }
            try { dacq.Disconnect(); } catch { }
        }

        string path = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "latency_csharp.csv");
        using (var w = new StreamWriter(path))
        {
            w.WriteLine("branch,metric,median_ms");
            foreach (var kv in results)
                w.WriteLine("csharp,{0},{1:F3}", kv.Key, kv.Value);
        }
        Console.WriteLine("\nWrote " + path);
        return 0;
    }

    static int ArgInt(string[] args, string name, int dflt)
    {
        int i = Array.IndexOf(args, name);
        int v;
        if (i >= 0 && i + 1 < args.Length && int.TryParse(args[i + 1], out v)) return v;
        return dflt;
    }

    // ------------------------------------------------------------- connect

    static bool Connect()
    {
        var list = new CMcsUsbListNet(DeviceEnumNet.MCS_DEVICE_USB);
        var entries = list.GetUsbListEntries();
        if (entries.Length == 0) { Console.WriteLine("  No MEA device found."); return false; }
        Console.WriteLine("  Found {0} device(s)", entries.Length);

        dacq = new CMeaUSBDeviceNet();
        dacq.ChannelDataEvent += OnChannelData;
        dacq.ErrorEvent += (msg, action) => Console.WriteLine("  DEVICE ERROR: " + msg);

        uint status = dacq.Connect(entries[0]);
        if (status != 0) { Console.WriteLine("  Connect failed: " + status); return false; }

        dacq.StopDacq(0);
        var scu = new CSCUFunctionNet(dacq);
        scu.SetDacqLegacyMode(false);

        dacq.SetSamplerate(SAMPLERATE, 0, 0);
        dacq.SetDataMode(DataModeEnumNet.Signed_32bit, 0);
        dacq.SetNumberOfAnalogChannels(NUM_CHANNELS, 0, 0, 8, 0);
        dacq.EnableChecksum(true, 0);

        int analog, digital, checksum, timestamp, cib;
        dacq.GetChannelLayout(out analog, out digital, out checksum,
                              out timestamp, out cib, 0);
        channelsInBlock = cib;
        Console.WriteLine("  Channel layout: {0} analog, {1} digital, {2} in block",
                          analog, digital, cib);

        dacq.ChannelBlock.SetSelectedChannels(
            channelsInBlock / 2, QUEUE_SIZE, THRESHOLD,
            SampleSizeNet.SampleSize32Signed,
            SampleDstSizeNet.SampleDstSize32,
            channelsInBlock);
        dacq.ChannelBlock.SetCommonThreshold(THRESHOLD);
        dacq.ChannelBlock.SetCheckChecksum((uint)checksum, (uint)timestamp);
        return true;
    }

    // ------------------------------------------------------------ callback

    // Same work as the Python handle_data_event, but with no marshalling:
    // ReadFramesI32 hands back a native int[] we can use directly.
    static void OnChannelData(CMcsUsbDacqNet d, int cbHandle, int numFrames)
    {
        double tEnter = Now();
        try
        {
            int n = Math.Min(channelsInBlock / 2, NUM_CHANNELS);
            var watch = new Dictionary<int, int[]>();
            for (int i = 0; i < n; i++)
            {
                int framesRet;
                int[] frames = d.ChannelBlock.ReadFramesI32(i, 0, numFrames, out framesRet);
                if (framesRet <= 0 || frames == null) continue;

                int take = Math.Min(2500, frames.Length);
                int off  = frames.Length - take;
                for (int k = 0; k < take; k++) dataBuffer[i, k] = frames[off + k];

                if (Array.IndexOf(WatchChannels, i) >= 0) watch[i] = frames;
            }
            lock (recentLock)
            {
                recent.Enqueue(new Snapshot { T = tEnter, Watch = watch });
                while (recent.Count > 40) recent.Dequeue();
            }
        }
        catch (Exception ex) { Console.WriteLine("  callback error: " + ex.Message); }
        finally
        {
            lock (callbackDurations)
            {
                callbackDurations.Add(Now() - tEnter);
                callbackTimes.Add(tEnter);
                frameCounts.Add(numFrames);
            }
        }
    }

    // ------------------------------------------------- phase: record-only

    static void PhaseRecord(int seconds, Dictionary<string, double> results)
    {
        Console.WriteLine("\n" + new string('=', 70));
        Console.WriteLine("PHASE - record-only timing ({0} s)", seconds);
        Console.WriteLine(new string('=', 70));

        dacq.StartDacq();
        var hashes = new List<int>();
        double tEnd = Now() + seconds * 1000.0;
        int reads = 0;

        while (Now() < tEnd)
        {
            int h = 17;
            unchecked
            {
                for (int i = 0; i < NUM_CHANNELS; i++)
                    for (int k = 0; k < 2500; k += 97) h = h * 31 + dataBuffer[i, k];
            }
            hashes.Add(h);
            reads++;
            Thread.Sleep(50);        // same 50 ms sleep run_cartpole.py uses today
        }
        dacq.StopDacq(0);

        int dup = 0;
        for (int i = 1; i < hashes.Count; i++) if (hashes[i] == hashes[i - 1]) dup++;

        var intervals = new List<double>();
        lock (callbackDurations)
            for (int i = 1; i < callbackTimes.Count; i++)
                intervals.Add(callbackTimes[i] - callbackTimes[i - 1]);

        double budget = THRESHOLD / (double)SAMPLERATE * 1000.0;

        Report("callback duration", callbackDurations, results);
        Report("callback interval", intervals, results);
        Console.WriteLine("  {0,-28} median {1:F0}", "frames per callback", Median(frameCounts.Select(x => (double)x).ToList()));
        Console.WriteLine("  {0,-28} {1}", "buffer reads", reads);
        Console.WriteLine("  {0,-28} {1} / {2} ({3:F0}%)", "duplicate consecutive reads",
                          dup, Math.Max(reads - 1, 1), 100.0 * dup / Math.Max(reads - 1, 1));

        double med = Median(callbackDurations);
        if (med > budget)
        {
            Console.WriteLine("\n  WARNING: callback takes {0:F1} ms but fires every {1:F0} ms.", med, budget);
            Console.WriteLine("           The ring buffer is overrunning and data is being lost silently.");
        }
    }

    // ------------------------------------------------- phase: round-trip

    static void PhaseRoundTrip(int amplitudeSteps, Dictionary<string, double> results)
    {
        Console.WriteLine("\n" + new string('=', 70));
        Console.WriteLine("PHASE - round-trip latency (SALINE ONLY)");
        Console.WriteLine(new string('=', 70));

        CStimulusFunctionNet stim;
        try { stim = new CStimulusFunctionNet(dacq); }
        catch (Exception ex)
        {
            Console.WriteLine("  Could not create CStimulusFunctionNet: " + ex.Message);
            return;
        }

        try
        {
            int vrange = stim.GetVoltageRangeInMicroVolt(0);
            int vres   = stim.GetVoltageResolutionInMicroVolt(0);
            Console.WriteLine("  Voltage range      : +/- {0} uV ({1:F2} V)", vrange, vrange / 1e6);
            Console.WriteLine("  Voltage resolution : {0} uV per step", vres);
            Console.WriteLine("  Requested amplitude: {0} steps = {1:F1} mV",
                              amplitudeSteps, amplitudeSteps * vres / 1000.0);
        }
        catch (Exception ex) { Console.WriteLine("  Could not query ranges: " + ex.Message); }

        // Biphasic pulse: +A for 200 us, -A for 200 us, then rest.
        int[]   amps = { amplitudeSteps, -amplitudeSteps, 0 };
        ulong[] durs = { 200, 200, 100000 };

        dacq.StartDacq();
        Thread.Sleep(1000);                       // baseline for the MAD estimate

        var mad = new Dictionary<int, double>();
        lock (recentLock)
        {
            foreach (int ch in WatchChannels)
            {
                var vals = recent.Where(s => s.Watch.ContainsKey(ch))
                                 .SelectMany(s => s.Watch[ch]).Select(v => (double)v).ToList();
                if (vals.Count > 0) mad[ch] = Math.Max(MedianAbsDev(vals), 1.0);
            }
        }
        if (mad.Count == 0) { Console.WriteLine("  No baseline captured."); dacq.StopDacq(0); return; }
        Console.WriteLine("  Baseline MAD: " + string.Join(", ", mad.Select(kv => "ch" + kv.Key + "=" + kv.Value.ToString("F0"))));

        var issueTimes = new List<double>();
        var latencies  = new List<double>();

        for (int pulse = 0; pulse < 10; pulse++)
        {
            lock (recentLock) recent.Clear();
            double t0 = Now();
            try
            {
                stim.PrepareAndSendData(0, amps, durs, STG_DestinationEnumNet.channeldata_voltage);
                stim.SendStart(1);
            }
            catch (Exception ex) { Console.WriteLine("  Stimulation call failed: " + ex.Message); break; }
            double tIssued = Now();
            issueTimes.Add(tIssued - t0);

            Thread.Sleep(500);

            double? found = null;
            List<Snapshot> snaps;
            lock (recentLock) snaps = recent.ToList();
            foreach (var s in snaps)
            {
                foreach (var kv in s.Watch)
                {
                    if (!mad.ContainsKey(kv.Key)) continue;
                    double m = Median(kv.Value.Select(v => (double)v).ToList());
                    for (int idx = 0; idx < kv.Value.Length; idx++)
                    {
                        if (Math.Abs(kv.Value[idx] - m) > ARTIFACT_SIGMA * mad[kv.Key])
                        {
                            double tArt = s.T - (kv.Value.Length - idx) / (double)SAMPLERATE * 1000.0;
                            found = tArt - t0;
                            break;
                        }
                    }
                    if (found.HasValue) break;
                }
                if (found.HasValue) break;
            }

            if (found.HasValue && found.Value > 0)
            {
                latencies.Add(found.Value);
                Console.WriteLine("  pulse {0,2}: issue {1,6:F2} ms   round-trip {2,7:F2} ms",
                                  pulse + 1, issueTimes.Last(), found.Value);
            }
            else
            {
                Console.WriteLine("  pulse {0,2}: issue {1,6:F2} ms   round-trip  no artifact found",
                                  pulse + 1, issueTimes.Last());
            }
        }
        dacq.StopDacq(0);

        if (issueTimes.Count > 0)
        {
            results["stim issue"] = Median(issueTimes);
            Console.WriteLine("\n  stim call returns in   : {0:F2} ms (median)", results["stim issue"]);
        }
        if (latencies.Count > 0)
        {
            results["round trip"] = Median(latencies);
            Console.WriteLine("  ROUND-TRIP LATENCY     : {0:F2} ms (median, n={1})",
                              results["round trip"], latencies.Count);
            Console.WriteLine("  STDP trace remaining   : {0:F2}%",
                              100.0 * Math.Exp(-results["round trip"] / 20.0));
        }
        else
        {
            Console.WriteLine("\n  No artifacts detected. Either stimulation did not fire, or the");
            Console.WriteLine("  amplitude is too small to see. Check the printed voltage range.");
        }
    }

    // ------------------------------------------------------------- helpers

    static void Report(string label, List<double> vals, Dictionary<string, double> results)
    {
        if (vals == null || vals.Count == 0) { Console.WriteLine("  {0,-28} (no data)", label); return; }
        double med = Median(vals);
        Console.WriteLine("  {0,-28} median {1,7:F2} ms   min {2,7:F2}   max {3,7:F2}   n={4}",
                          label, med, vals.Min(), vals.Max(), vals.Count);
        results[label] = med;
    }

    static double Median(List<double> v)
    {
        if (v == null || v.Count == 0) return 0;
        var s = v.OrderBy(x => x).ToList();
        int m = s.Count / 2;
        return s.Count % 2 == 1 ? s[m] : (s[m - 1] + s[m]) / 2.0;
    }

    static double MedianAbsDev(List<double> v)
    {
        double m = Median(v);
        return Median(v.Select(x => Math.Abs(x - m)).ToList());
    }
}
