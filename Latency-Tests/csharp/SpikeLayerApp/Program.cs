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
    static int THRESHOLD   = SAMPLERATE / 10;   // callback every 100 ms (20 ms in --serve mode)
    const int SERVE_CHUNK_MS = 20;              // --serve: same 20 ms chunks as mea_device.py
    const double ARTIFACT_SIGMA = 8.0;

    static readonly int[] WatchChannels = { 0, 1, 30, 31 };

    static CMeaUSBDeviceNet dacq;
    static CMcsUsbListEntryNet usbEntry;        // kept so the stimulator can connect to the same device
    static Recording recording;                 // --serve only: ring buffer + session files
    static readonly object readLock = new object();   // held while a callback reads the DLL queues
    static int channelsInBlock;

    // timing state, written from the DLL's callback thread --> changfed to add in scale factor and 5000 not 2500
    static readonly List<double> callbackDurations = new List<double>();
    static readonly List<double> callbackTimes     = new List<double>();
    static readonly List<int>    frameCounts       = new List<int>();
    // Latest 100 ms callback per channel: THRESHOLD (5,000) samples at 50 kHz, in uV.
    static double[,] dataBuffer = new double[NUM_CHANNELS, THRESHOLD];

    // uV per raw AD unit. Overwritten in Connect() from GetResolutionPerDigit;
    // 0.1042 is the fallback if that query fails or returns something implausible.
    const double FALLBACK_UV_PER_DIGIT = 0.1042;
    static double dynamicConversionFactor = FALLBACK_UV_PER_DIGIT;

    // error counters for the long recording check (written from the DLL's callback thread)
    static int deviceErrors;    // ErrorEvent fired by the DLL
    static int callbackErrors;  // exception inside OnChannelData
    static int shortReads;      // a channel returned fewer frames than the callback announced
    static int lateCallbacks;   // callback carried more than 100 ms of data (we fell behind)

    // recent frames on the watched channels, for artifact search
    class Snapshot { public double T; public Dictionary<int,int[]> Watch; }
    static readonly Queue<Snapshot> recent = new Queue<Snapshot>();
    static readonly object recentLock = new object();

    static readonly Stopwatch clock = Stopwatch.StartNew();
    static double Now() { return clock.Elapsed.TotalMilliseconds; }

    // ------------------------------------------------------------------ main

    static int Main(string[] args)
    {
        if (args.Contains("--serve")) return Serve();

        bool doStim    = args.Contains("--stim");
        int  stimSteps = ArgInt(args, "--stim-steps", 100);
        int  seconds   = ArgInt(args, "--seconds", 10);
        int  minutes   = ArgInt(args, "--minutes", 0);   // >0 = long recording check

        var results = new Dictionary<string, double>();

        Console.WriteLine(new string('=', 70));
        Console.WriteLine("BRANCH B - native C# path");
        Console.WriteLine(new string('=', 70));

        if (!Connect()) return 1;

        // "Done when: it records for 10 minutes with no errors"  ->  SpikeLayerApp.exe --minutes 10
        if (minutes > 0)
        {
            bool pass = false;
            try { pass = PhaseLongRecording(minutes); }
            finally
            {
                try { dacq.StopDacq(0); } catch { }
                try { dacq.Disconnect(); } catch { }
            }
            return pass ? 0 : 2;
        }

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
        dacq.ErrorEvent += (msg, action) =>
        {
            Interlocked.Increment(ref deviceErrors);
            Console.WriteLine("  DEVICE ERROR: " + msg);
        };

        usbEntry = entries[0];
        dataBuffer = new double[NUM_CHANNELS, THRESHOLD];
        uint status = dacq.Connect(usbEntry);
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
        // Get the real uV-per-AD-unit from the recording hardware before data starts.
        QueryVoltageResolution();

        dacq.ChannelBlock.SetSelectedChannels(
            channelsInBlock / 2, QUEUE_SIZE, THRESHOLD,
            SampleSizeNet.SampleSize32Signed,
            SampleDstSizeNet.SampleDstSize32,
            channelsInBlock);
        dacq.ChannelBlock.SetCommonThreshold(THRESHOLD);
        dacq.ChannelBlock.SetCheckChecksum((uint)checksum, (uint)timestamp);
        return true;
    }

    // Ask the recording ADC how many volts one AD unit is worth.
    // ASSUMPTION (unverified until the rig is powered): resUnit is a power-of-ten
    // exponent relative to volts, so uV/digit = res * 10^(resUnit + 6).
    // The raw values are printed so the first powered run can confirm or refute this.
    static void QueryVoltageResolution()
    {
        try
        {
            int res, resUnit;
            uint status = dacq.GetResolutionPerDigit(
                0, DacqGroupChannelEnumNet.HeadstageElectrodeGroup, out res, out resUnit);
            Console.WriteLine("  GetResolutionPerDigit: status={0} res={1} resUnit={2}",
                              status, res, resUnit);

            // The DLL reports the physical unit (Volt/Ampere/...) separately, which is
            // why resUnit is assumed to be only the power-of-ten. Expect "Volt" here.
            try
            {
                AnalogUnitEnumNet unit;
                dacq.GetAnalogValueUnit(0, DacqGroupChannelEnumNet.HeadstageElectrodeGroup, out unit);
                Console.WriteLine("  GetAnalogValueUnit: {0}", unit);
            }
            catch (Exception ex) { Console.WriteLine("  GetAnalogValueUnit failed: " + ex.Message); }

            double uv = res * Math.Pow(10, resUnit + 6);
            if (status != 0)
                Console.WriteLine("  Non-zero status; keeping fallback.");
            else if (!(uv >= 0.001 && uv <= 100.0))
                Console.WriteLine("  Computed {0:G4} uV/digit is outside 0.001-100 uV; " +
                                  "resUnit is probably not a power-of-ten exponent. Keeping fallback.", uv);
            else
                dynamicConversionFactor = uv;
        }
        catch (Exception ex)
        {
            Console.WriteLine("  GetResolutionPerDigit failed: " + ex.Message);
        }
        Console.WriteLine("  Using {0:F4} uV per AD unit{1}", dynamicConversionFactor,
                          dynamicConversionFactor == FALLBACK_UV_PER_DIGIT ? " (FALLBACK)" : "");
    }

    // ------------------------------------------------------------ callback


    // Same work as the Python handle_data_event, but with no marshalling:
    // ReadFramesI32 hands back a native int[] we can use directly.
    static void OnChannelData(CMcsUsbDacqNet d, int cbHandle, int numFrames)
    {
        double tEnter = Now();
        try
        {
            if (numFrames > THRESHOLD) Interlocked.Increment(ref lateCallbacks);
            int n = Math.Min(channelsInBlock / 2, NUM_CHANNELS);
            var watch = new Dictionary<int, int[]>();
            var rec = recording;
            var all = new int[n][];
            int fewest = numFrames;
            lock (readLock)
            {
                for (int i = 0; i < n; i++)
                {
                    int framesRet;
                    int[] frames = d.ChannelBlock.ReadFramesI32(i, 0, numFrames, out framesRet);
                    if (framesRet < numFrames || frames == null) Interlocked.Increment(ref shortReads);
                    if (frames == null) framesRet = 0;
                    fewest = Math.Min(fewest, framesRet);
                    all[i] = frames;
                    if (framesRet <= 0 || frames == null) continue;

                    // Keep every sample of the 100 ms read (5,000 at 50 kHz), scaled to uV.
                    // No (int) cast: that would throw away sub-uV precision.
                    int take = Math.Min(Math.Min(THRESHOLD, framesRet), frames.Length);
                    for (int k = 0; k < take; k++) dataBuffer[i, k] = frames[k] * dynamicConversionFactor;

                    if (Array.IndexOf(WatchChannels, i) >= 0) watch[i] = frames;
                }
                // --serve: every channel must give the same number of frames, or the
                // channels would drift out of line in the session file.
                if (rec != null)
                {
                    if (fewest < numFrames)
                        Console.WriteLine("  WARNING: a channel returned {0} of {1} frames; saving {0}", fewest, numFrames);
                    rec.Append(all, fewest);
                }
            }
            lock (recentLock)
            {
                recent.Enqueue(new Snapshot { T = tEnter, Watch = watch });
                while (recent.Count > 40) recent.Dequeue();
            }
        }
        catch (Exception ex)
        {
            Interlocked.Increment(ref callbackErrors);
            Console.WriteLine("  callback error: " + ex.Message);
        }
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

    // ------------------------------------------------------------- --serve

    // TCP server for the game loop (see SpikeServer.cs and spike_client.py).
    static int Serve()
    {
        Console.WriteLine(new string('=', 70));
        Console.WriteLine("SPIKE SERVER - plays waves, records, counts spikes");
        Console.WriteLine(new string('=', 70));

        THRESHOLD = SAMPLERATE * SERVE_CHUNK_MS / 1000;
        if (!Connect()) return 1;
        if (channelsInBlock / 2 < NUM_CHANNELS)
        {
            Console.WriteLine("  Only {0} data streams; the server needs {1}.", channelsInBlock / 2, NUM_CHANNELS);
            try { dacq.Disconnect(); } catch { }
            return 1;
        }

        Stimulator stim;
        try { stim = new Stimulator(usbEntry); }
        catch (Exception ex)
        {
            Console.WriteLine("  Stimulator setup failed: " + ex.Message);
            try { dacq.Disconnect(); } catch { }
            return 1;
        }

        recording = new Recording(SAMPLERATE, 12, dynamicConversionFactor,
                                  dynamicConversionFactor == FALLBACK_UV_PER_DIGIT);
        string dir = Path.Combine(Environment.CurrentDirectory, "sessions");
        var server = new SpikeServer(recording, stim, CurrentFrame, dir);
        Console.CancelKeyPress += (s, e) => { e.Cancel = true; Console.WriteLine("  Stopping..."); server.Stop(); };

        dacq.StartDacq();
        try { server.Run(); }
        finally
        {
            recording.EndSession();
            try { dacq.StopDacq(0); } catch { }
            stim.Dispose();
            try { dacq.Disconnect(); } catch { }
        }
        return 0;
    }

    // Frame being recorded right now = frames already handed to `recording`
    // + frames still waiting in the DLL's queue (channel 0). Still behind the
    // electrodes by the USB transfer delay; see README.
    static long CurrentFrame()
    {
        lock (readLock)
        {
            long have = recording.Total;
            try { return have + dacq.ChannelBlock.AvailFrames(0, 0); }
            catch { return have; }
        }
    }

    // ------------------------------------------- phase: long recording check

    // Records for `minutes`, printing a status line every minute, then PASS/FAIL.
    // FAIL if any device error, callback exception, short read, a gap between
    // callbacks over 200 ms, or fewer than 95% of the expected callbacks.
    static bool PhaseLongRecording(int minutes)
    {
        Console.WriteLine("\n" + new string('=', 70));
        Console.WriteLine("PHASE - long recording check ({0} min)", minutes);
        Console.WriteLine(new string('=', 70));

        double tStart = Now();
        double tEnd = tStart + minutes * 60000.0;
        double nextStatus = tStart + 60000.0;
        dacq.StartDacq();

        while (Now() < tEnd)
        {
            Thread.Sleep(250);
            if (Now() >= nextStatus)
            {
                int cbs; lock (callbackDurations) cbs = callbackTimes.Count;
                double med, lo, hi; int flat;
                NoiseSummary(out med, out lo, out hi, out flat);
                Console.WriteLine("  {0,3:F0} min  callbacks {1,6}  errors dev/cb/short {2}/{3}/{4}  " +
                                  "noise median {5:F2} uV (min {6:F2}, max {7:F2})  flat ch {8}",
                                  (Now() - tStart) / 60000.0, cbs, deviceErrors, callbackErrors,
                                  shortReads, med, lo, hi, flat);
                nextStatus += 60000.0;
            }
        }
        dacq.StopDacq(0);

        // callback gaps
        double budget = THRESHOLD / (double)SAMPLERATE * 1000.0;   // 100 ms
        int gaps = 0; double worstGap = 0; int count;
        lock (callbackDurations)
        {
            count = callbackTimes.Count;
            for (int i = 1; i < callbackTimes.Count; i++)
            {
                double dt = callbackTimes[i] - callbackTimes[i - 1];
                if (dt > worstGap) worstGap = dt;
                if (dt > 2 * budget) gaps++;
            }
        }
        int expected = (int)(minutes * 60000.0 / budget);

        double nMed, nLo, nHi; int nFlat;
        NoiseSummary(out nMed, out nLo, out nHi, out nFlat);

        Console.WriteLine();
        Console.WriteLine("  {0,-32} {1}", "conversion", dynamicConversionFactor.ToString("F4") + " uV/AD unit" +
                          (dynamicConversionFactor == FALLBACK_UV_PER_DIGIT ? " (FALLBACK)" : ""));
        Console.WriteLine("  {0,-32} {1} / {2} expected", "callbacks", count, expected);
        Console.WriteLine("  {0,-32} {1}", "device errors", deviceErrors);
        Console.WriteLine("  {0,-32} {1}", "callback exceptions", callbackErrors);
        Console.WriteLine("  {0,-32} {1}", "short reads", shortReads);
        Console.WriteLine("  {0,-32} {1}  (worst {2:F1} ms)", "gaps > 200 ms", gaps, worstGap);
        Console.WriteLine("  {0,-32} {1}", "late callbacks (warning only)", lateCallbacks);
        Console.WriteLine("  {0,-32} median {1:F2}  min {2:F2}  max {3:F2}", "noise RMS uV (last 100 ms)", nMed, nLo, nHi);
        Console.WriteLine("  {0,-32} {1}", "flat channels (warning only)", nFlat);
        if (nMed > 0 && (nMed < 1 || nMed > 30))
            Console.WriteLine("  WARNING: saline noise is usually a few uV RMS. {0:F2} uV suggests the " +
                              "conversion factor is off - send res/resUnit from the startup lines.", nMed);

        bool pass = deviceErrors == 0 && callbackErrors == 0 && shortReads == 0
                    && gaps == 0 && count >= 0.95 * expected;
        Console.WriteLine("\n  RESULT: {0}", pass ? "PASS" : "FAIL");
        return pass;
    }

    // Per-channel RMS (mean removed) of the most recent 100 ms in dataBuffer, in uV.
    // Reads while the callback may be writing; fine for a status readout.
    static void NoiseSummary(out double median, out double min, out double max, out int flat)
    {
        var rms = new List<double>();
        flat = 0;
        for (int i = 0; i < NUM_CHANNELS; i++)
        {
            double sum = 0, sumSq = 0;
            for (int k = 0; k < THRESHOLD; k++) { double v = dataBuffer[i, k]; sum += v; sumSq += v * v; }
            double mean = sum / THRESHOLD;
            double r = Math.Sqrt(Math.Max(sumSq / THRESHOLD - mean * mean, 0));
            if (r < 0.01) flat++;
            rms.Add(r);
        }
        median = Median(rms); min = rms.Min(); max = rms.Max();
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
                    for (int k = 0; k < 5000; k += 97) h = h * 31 + (int)dataBuffer[i, k];//make k<5000 so that 5000 tests not 2500!
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