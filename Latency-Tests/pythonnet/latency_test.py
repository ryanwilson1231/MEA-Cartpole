"""
Branch A — pythonnet path.

Measures how long a closed-loop cycle takes when the control code is Python and
every hardware call crosses the pythonnet -> .NET boundary.

    python latency_test.py                   marshalling bench only (no hardware)
    python latency_test.py --hardware        + record-only timing
    python latency_test.py --hardware --stim + round-trip latency   (SALINE ONLY)

Writes latency_pythonnet.csv next to this file.
"""
import argparse
import csv
import os
import statistics
import subprocess
import sys
import time
from collections import deque

import numpy as np

# Where McsUsbNet.dll lives. Adjust if you move things.
DLL_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "Hardware-Pythonnet-Path")
)

SAMPLERATE = 50_000
NUM_CHANNELS = 60
QUEUE_SIZE = SAMPLERATE          # 1 s ring buffer per channel
THRESHOLD = SAMPLERATE // 10     # callback every 100 ms  <-- the knob that sets the floor

# Channels watched for the stimulation artifact during the round-trip test.
WATCH_CHANNELS = (0, 1, 30, 31)
ARTIFACT_SIGMA = 8               # artifact = |sample| > this many MADs above baseline


# --------------------------------------------------------------------------- setup

def unblock_dll(path):
    """Strip the mark-of-the-web so .NET will load the assembly.

    The DLL was downloaded and lives under OneDrive, so .NET treats it as a
    remote assembly and refuses to load it. Unblock-File removes that marker.
    """
    if not os.path.exists(path):
        print(f"  DLL not found at {path}")
        return False
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", f"Unblock-File -Path '{path}'"],
            check=True, capture_output=True, timeout=30,
        )
        print("  Unblock-File: ok")
        return True
    except Exception as exc:
        print(f"  Unblock-File failed ({exc}) - may need to run it manually")
        return False


def check_environment():
    print("=" * 70)
    print("ENVIRONMENT")
    print("=" * 70)
    bits = "64-bit" if sys.maxsize > 2 ** 32 else "32-BIT (will not load this DLL)"
    print(f"  Python      : {sys.version.split()[0]}  {bits}")
    try:
        import importlib.metadata as md
        print(f"  pythonnet   : {md.version('pythonnet')}")
    except Exception:
        print("  pythonnet   : NOT INSTALLED  ->  pip install pythonnet")
        return False
    print(f"  DLL folder  : {DLL_DIR}")
    unblock_dll(os.path.join(DLL_DIR, "McsUsbNet.dll"))
    return True


def load_dll():
    """Import the MCS namespace. Returns the Mcs.Usb module."""
    sys.path.append(DLL_DIR)
    import clr
    clr.AddReference("McsUsbNet")
    import Mcs.Usb as mcs
    return mcs


# ----------------------------------------------------------- phase 1: marshalling

def bench_marshalling(n_frames=5000, n_channels=60, repeats=5):
    """Cost of moving a .NET int[] into Python, three ways.

    This is the operation handle_data_event does 60x per callback via list().
    Runs without hardware.
    """
    print()
    print("=" * 70)
    print("PHASE 1 - pythonnet marshalling cost (no hardware needed)")
    print("=" * 70)

    import System
    from System.Runtime.InteropServices import Marshal

    net_array = System.Array.CreateInstance(System.Int32, n_frames)
    for i in range(n_frames):
        net_array[i] = i

    def via_list():
        return np.array(list(net_array))

    def via_fromiter():
        return np.fromiter(net_array, dtype=np.int32, count=n_frames)

    def via_marshal():
        # Bulk memcpy straight into numpy's buffer - one interop call instead
        # of one per element. This is what handle_data_event should be doing.
        out = np.empty(n_frames, dtype=np.int32)
        Marshal.Copy(net_array, 0, System.IntPtr.op_Explicit(
            System.Int64(out.ctypes.data)), n_frames)
        return out

    results = {}
    for name, fn in (("list() [current code]", via_list),
                     ("np.fromiter", via_fromiter),
                     ("Marshal.Copy (bulk)", via_marshal)):
        try:
            times = []
            for _ in range(repeats):
                t0 = time.perf_counter()
                fn()
                times.append((time.perf_counter() - t0) * 1000.0)
            per_call = statistics.median(times)
            results[name] = per_call
            print(f"  {name:<24} {per_call:7.2f} ms/channel"
                  f"   -> {per_call * n_channels:8.1f} ms for {n_channels} channels")
        except Exception as exc:
            print(f"  {name:<24} failed: {exc}")

    budget = THRESHOLD / SAMPLERATE * 1000.0
    print(f"\n  Callback budget: {budget:.0f} ms (threshold {THRESHOLD} frames @ {SAMPLERATE} Hz)")
    cur = results.get("list() [current code]")
    if cur is not None:
        total = cur * n_channels
        verdict = "OVER BUDGET - ring buffer will overrun" if total > budget else "within budget"
        print(f"  Current approach: {total:.1f} ms  ->  {verdict}")
    return results


# ------------------------------------------------------------- hardware harness

class Recorder:
    """Thin wrapper that connects, records, and timestamps every callback."""

    def __init__(self, mcs):
        self.mcs = mcs
        self.dacq = None
        self.stim = None
        self.channels_in_block = 0

        self.callback_durations = []   # ms spent inside handle_data_event
        self.callback_times = []       # perf_counter at callback entry
        self.frame_counts = []
        self.data_buffer = np.zeros((NUM_CHANNELS, 2500))
        # (t_callback, frames_for_watch_channels) for artifact search
        self.recent = deque(maxlen=40)

    # -- connection ---------------------------------------------------------

    def connect(self):
        mcs = self.mcs
        lst = mcs.CMcsUsbListNet(mcs.DeviceEnumNet.MCS_DEVICE_USB)
        entries = lst.GetUsbListEntries()
        if len(entries) == 0:
            print("  No MEA device found.")
            return False
        print(f"  Found {len(entries)} device(s)")

        self.dacq = mcs.CMeaUSBDeviceNet()
        self.dacq.ChannelDataEvent += self._on_data
        self.dacq.ErrorEvent += lambda msg, action: print(f"  DEVICE ERROR: {msg}")

        status = self.dacq.Connect(entries[0])
        if status != 0:
            print(f"  Connect failed: {status}")
            return False

        self._configure()
        self.entry = entries[0]
        return True

    def _configure(self):
        mcs = self.mcs
        from System import Int32

        self.dacq.StopDacq(0)
        scu = mcs.CSCUFunctionNet(self.dacq)
        scu.SetDacqLegacyMode(False)

        self.dacq.SetSamplerate(SAMPLERATE, 0, 0)
        self.dacq.SetDataMode(mcs.DataModeEnumNet.Signed_32bit, 0)
        self.dacq.SetNumberOfAnalogChannels(NUM_CHANNELS, 0, 0, 8, 0)
        self.dacq.EnableChecksum(True, 0)

        a, d, c, t, cib = (Int32(0),) * 5
        a, d, c, t, cib = self.dacq.GetChannelLayout(a, d, c, t, cib, 0)
        self.channels_in_block = int(cib)
        print(f"  Channel layout: {int(a)} analog, {int(d)} digital, "
              f"{self.channels_in_block} in block")

        self.dacq.ChannelBlock.SetSelectedChannels(
            self.channels_in_block // 2, QUEUE_SIZE, THRESHOLD,
            mcs.SampleSizeNet.SampleSize32Signed,
            mcs.SampleDstSizeNet.SampleDstSize32,
            self.channels_in_block,
        )
        self.dacq.ChannelBlock.SetCommonThreshold(THRESHOLD)
        self.dacq.ChannelBlock.SetCheckChecksum(int(c), int(t))

    # -- the callback -------------------------------------------------------

    def _on_data(self, dacq, cb_handle, num_frames):
        """Mirrors handle_data_event in mea_integeration.py, with timing."""
        t_enter = time.perf_counter()
        from System import Int32
        try:
            n = min(self.channels_in_block // 2, NUM_CHANNELS)
            watch = {}
            for i in range(n):
                frames_ret = Int32(0)
                data = dacq.ChannelBlock.ReadFramesI32(i, 0, num_frames, frames_ret)
                if int(frames_ret) <= 0:
                    continue
                arr = np.array(list(data[0]))          # the expensive line
                if len(arr) >= 2500:
                    self.data_buffer[i] = arr[-2500:]
                else:
                    self.data_buffer[i] = np.pad(arr, (0, 2500 - len(arr)))
                if i in WATCH_CHANNELS:
                    watch[i] = arr
            self.recent.append((t_enter, watch))
        except Exception as exc:
            print(f"  callback error: {exc}")
        finally:
            self.callback_durations.append((time.perf_counter() - t_enter) * 1000.0)
            self.callback_times.append(t_enter)
            self.frame_counts.append(num_frames)

    # -- lifecycle ----------------------------------------------------------

    def start(self):
        self.dacq.StartDacq()

    def stop(self):
        try:
            self.dacq.StopDacq(0)
        finally:
            self.dacq.Disconnect()


# --------------------------------------------------- phase 2: record-only timing

def phase_record(rec, seconds=10):
    print()
    print("=" * 70)
    print(f"PHASE 2 - record-only timing ({seconds} s)")
    print("=" * 70)

    rec.start()
    hashes = []
    t_end = time.perf_counter() + seconds
    reads = 0
    decode_times = []

    sys.path.append(DLL_DIR)          # spike.py lives beside the DLL
    try:
        from spike import MADs, count_spikes
        have_spike = True
    except Exception:
        have_spike = False

    while time.perf_counter() < t_end:
        buf = rec.data_buffer.copy()
        hashes.append(hash(buf.tobytes()))
        reads += 1
        if have_spike:
            t0 = time.perf_counter()
            tax = np.linspace(0, buf.shape[1] / SAMPLERATE, buf.shape[1])
            mads, absact, _, _ = MADs(tax, buf)
            count_spikes(absact, mads, 3)
            decode_times.append((time.perf_counter() - t0) * 1000.0)
        time.sleep(0.05)              # the sleep that is in run_cartpole.py today

    rec.stop()

    dup = sum(1 for a, b in zip(hashes, hashes[1:]) if a == b)
    intervals = [(b - a) * 1000.0 for a, b in zip(rec.callback_times, rec.callback_times[1:])]
    budget = THRESHOLD / SAMPLERATE * 1000.0

    out = {}
    def report(label, values, unit="ms"):
        if not values:
            print(f"  {label:<28} (no data)")
            return
        med = statistics.median(values)
        print(f"  {label:<28} median {med:7.2f} {unit}   "
              f"min {min(values):7.2f}   max {max(values):7.2f}   n={len(values)}")
        out[label] = med

    report("callback duration", rec.callback_durations)
    report("callback interval", intervals)
    report("decode (MADs+count)", decode_times)
    print(f"  {'frames per callback':<28} median {statistics.median(rec.frame_counts):.0f}")
    print(f"  {'buffer reads':<28} {reads}")
    print(f"  {'duplicate consecutive reads':<28} {dup} / {max(reads - 1, 1)} "
          f"({100.0 * dup / max(reads - 1, 1):.0f}%)")

    if rec.callback_durations:
        med = statistics.median(rec.callback_durations)
        if med > budget:
            print(f"\n  WARNING: callback takes {med:.1f} ms but fires every {budget:.0f} ms.")
            print("           The ring buffer is overrunning and data is being lost silently.")
    return out


# ------------------------------------------------- phase 3: round-trip latency

def phase_roundtrip(rec, mcs, amplitude_steps, n_pulses=10):
    """Stimulate, then find the artifact in the recording. SALINE ONLY."""
    print()
    print("=" * 70)
    print("PHASE 3 - round-trip latency (SALINE ONLY)")
    print("=" * 70)

    try:
        stim = mcs.CStimulusFunctionNet(rec.dacq)
    except Exception as exc:
        print(f"  Could not create CStimulusFunctionNet: {exc}")
        return {}

    # Settle the units question with the device's own numbers.
    try:
        vrange = stim.GetVoltageRangeInMicroVolt(0)
        vres = stim.GetVoltageResolutionInMicroVolt(0)
        print(f"  Voltage range      : +/- {vrange} uV  ({vrange / 1e6:.2f} V)")
        print(f"  Voltage resolution : {vres} uV per step")
        print(f"  Requested amplitude: {amplitude_steps} steps "
              f"= {amplitude_steps * vres / 1000.0:.1f} mV")
    except Exception as exc:
        print(f"  Could not query ranges: {exc}")

    from System import Array, Int32, UInt64

    # Biphasic pulse: +A for 200 us, -A for 200 us, then rest.
    amps = Array[Int32]([amplitude_steps, -amplitude_steps, 0])
    durs = Array[UInt64]([UInt64(200), UInt64(200), UInt64(100_000)])

    rec.start()
    time.sleep(1.0)                                   # baseline for the MAD estimate
    baseline = {ch: np.concatenate([w[ch] for _, w in rec.recent if ch in w][-5:])
                for ch in WATCH_CHANNELS
                if any(ch in w for _, w in rec.recent)}
    mad = {ch: max(np.median(np.abs(v - np.median(v))), 1.0) for ch, v in baseline.items()}
    if not mad:
        print("  No baseline data captured - is the device streaming?")
        rec.stop()
        return {}
    print(f"  Baseline MAD: " + ", ".join(f"ch{c}={m:.0f}" for c, m in mad.items()))

    issue_times, latencies = [], []
    for pulse in range(n_pulses):
        mark = len(rec.recent)
        t0 = time.perf_counter()
        try:
            stim.PrepareAndSendData(
                0, amps, durs, mcs.STG_DestinationEnumNet.channeldata_voltage)
            stim.SendStart(1)
        except Exception as exc:
            print(f"  Stimulation call failed: {exc}")
            break
        t_issued = time.perf_counter()
        issue_times.append((t_issued - t0) * 1000.0)

        time.sleep(0.5)                               # let the artifact land and arrive

        found = None
        for t_cb, watch in list(rec.recent)[mark:]:
            for ch, arr in watch.items():
                if ch not in mad:
                    continue
                hits = np.nonzero(np.abs(arr - np.median(arr)) > ARTIFACT_SIGMA * mad[ch])[0]
                if len(hits):
                    # frames in this callback end at ~t_cb
                    t_art = t_cb - (len(arr) - hits[0]) / SAMPLERATE
                    found = (t_art - t0) * 1000.0
                    break
            if found is not None:
                break

        if found is not None and found > 0:
            latencies.append(found)
            print(f"  pulse {pulse + 1:2d}: issue {issue_times[-1]:6.2f} ms   "
                  f"round-trip {found:7.2f} ms")
        else:
            print(f"  pulse {pulse + 1:2d}: issue {issue_times[-1]:6.2f} ms   "
                  f"round-trip  no artifact found")

    rec.stop()

    out = {}
    if issue_times:
        out["stim issue"] = statistics.median(issue_times)
        print(f"\n  stim call returns in   : {out['stim issue']:.2f} ms (median)")
    if latencies:
        out["round trip"] = statistics.median(latencies)
        print(f"  ROUND-TRIP LATENCY     : {out['round trip']:.2f} ms (median, n={len(latencies)})")
        print(f"  STDP trace remaining   : {100 * np.exp(-out['round trip'] / 20.0):.2f}%")
    else:
        print("\n  No artifacts detected. Either stimulation did not fire, or the")
        print("  amplitude is too small to see. Check the printed voltage range.")
    return out


# ---------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hardware", action="store_true", help="run phases needing the MEA")
    ap.add_argument("--stim", action="store_true", help="round-trip test (SALINE ONLY)")
    ap.add_argument("--stim-steps", type=int, default=100,
                    help="stim amplitude in DAC steps (default 100, deliberately small)")
    ap.add_argument("--seconds", type=int, default=10, help="record-only duration")
    args = ap.parse_args()

    if not check_environment():
        return 1

    results = {}
    try:
        mcs = load_dll()
        print("  McsUsbNet  : loaded")
    except Exception as exc:
        print(f"  McsUsbNet  : FAILED TO LOAD\n    {exc}")
        return 1

    for k, v in bench_marshalling().items():
        results[f"marshal: {k}"] = v

    if args.hardware:
        rec = Recorder(mcs)
        print()
        print("=" * 70)
        print("CONNECTING")
        print("=" * 70)
        if not rec.connect():
            return 1
        results.update(phase_record(rec, args.seconds))
        if args.stim:
            rec2 = Recorder(mcs)
            if rec2.connect():
                results.update(phase_roundtrip(rec2, mcs, args.stim_steps))
    else:
        print("\n  (skipping hardware phases - pass --hardware)")

    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "latency_pythonnet.csv")
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["branch", "metric", "median_ms"])
        for k, v in results.items():
            w.writerow(["pythonnet", k, f"{v:.3f}"])
    print(f"\nWrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
