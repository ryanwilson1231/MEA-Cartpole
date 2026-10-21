"""
Real MEA2100-Mini-60 via pythonnet + McsUsbNet.dll (Windows lab PC only). Abbas, Oct 21 2026 (new).

Every DLL call here is copied from Baseline-Protocol/Hardware/mea_device.py (which follows MCS's
MEA2100_Recording_and_Stimulation example) and checked against the DLL's type list on Oct 21:
  CStg200xDownloadNet -> SetElectrodeMode/Enable/DacMux, SetBlankingEnable,
  SetEnableAmplifierProtectionSwitch, SetVoltageMode(channel), SetCurrentMode(channel),
  SetupTrigger, PrepareAndSendData, Stimulus.CreateSideband, SendStart, STG_DestinationEnumNet.
What is NEW compared with mea_device.py (and why):
  1. records ALL streams to disk, not only the 60 analog ones (sideband marks exact pulse times)
  2. current mode + cathodic-first trains (team decision)
  3. per-electrode routing so we can stimulate 1, 2 or 30 electrodes (sweep / moved-zones rows)
  4. blanking can be switched off for the optional R4 row
  5. sets the mode on BOTH generator channels. mea_device.py calls SetVoltageMode(0), which looks
     like it only sets channel 0 (generator 1); probe_api.py lets you confirm this.
Nothing here has been run on hardware yet. Run probe_api.py first, then the protocol on the
Test-60MEA probe or saline only.
"""
import threading
import time
from pathlib import Path

import numpy as np

from . import config as C
from .recorder import RawBlockWriter
from .stim_pulses import silent


def default_dll_path():
    here = Path(__file__).resolve()
    for p in [here.parent, *here.parents]:
        cand = p / "Baseline-Protocol" / "Hardware" / "McsUsbNet.dll"
        if cand.exists():
            return cand
        cand = p / "McsUsbNet.dll"
        if cand.exists():
            return cand
    raise FileNotFoundError("McsUsbNet.dll not found - pass dll_path=")


class MCSDevice:
    name = "mcs"

    def __init__(self, dll_path=None, frames_per_chunk=None):
        import clr
        clr.AddReference(str(dll_path or default_dll_path()))
        from System import Int32, UInt32, UInt64, Array, IntPtr
        from System.Runtime.InteropServices import Marshal
        from Mcs.Usb import (CMcsUsbListNet, DeviceEnumNet, CMeaUSBDeviceNet, CStg200xDownloadNet,
                             CSCUFunctionNet, DataModeEnumNet, DigitalDatastreamEnableEnumNet,
                             ChannelBlockTypeNet, SampleSizeNet, SampleDstSizeNet,
                             ElectrodeModeEnumNet, ElectrodeDacMuxEnumNet, STG_DestinationEnumNet)
        self.N = dict(Int32=Int32, UInt32=UInt32, UInt64=UInt64, Array=Array, IntPtr=IntPtr, Marshal=Marshal,
                      CMcsUsbListNet=CMcsUsbListNet, DeviceEnumNet=DeviceEnumNet, CMeaUSBDeviceNet=CMeaUSBDeviceNet,
                      CStg200xDownloadNet=CStg200xDownloadNet, CSCUFunctionNet=CSCUFunctionNet,
                      DataModeEnumNet=DataModeEnumNet, DigitalDatastreamEnableEnumNet=DigitalDatastreamEnableEnumNet,
                      ChannelBlockTypeNet=ChannelBlockTypeNet, SampleSizeNet=SampleSizeNet,
                      SampleDstSizeNet=SampleDstSizeNet, ElectrodeModeEnumNet=ElectrodeModeEnumNet,
                      ElectrodeDacMuxEnumNet=ElectrodeDacMuxEnumNet, STG_DestinationEnumNet=STG_DestinationEnumNet)
        self.fs = C.SAMPLE_RATE
        self._frames = frames_per_chunk or self.fs * 20 // 1000   # 20 ms chunks like mea_device.py
        self.dacq = self.stg = None
        self.writer = None
        self._lock = threading.Lock()
        self.n_streams = None
        self.read_streams = None
        self.read_error = None
        self.mode = None

    # ---------------- setup (mirrors mea_device.py) ----------------
    def connect(self):
        N = self.N
        devices = N["CMcsUsbListNet"](N["DeviceEnumNet"].MCS_DEVICE_USB)
        if devices.Count == 0:
            raise RuntimeError("No MEA found. Is it plugged in and switched on?")
        entry = devices.GetUsbListEntry(0)
        self.dacq = N["CMeaUSBDeviceNet"]()
        self.dacq.ChannelDataEvent += self._on_data
        self.dacq.ErrorEvent += lambda msg, action: print("MEA error:", msg)
        status = self.dacq.Connect(entry)
        if status != 0:
            raise RuntimeError(f"Could not connect to MEA (status {status})")
        self.stg = N["CStg200xDownloadNet"]()
        self.stg.Connect(entry)
        self._setup_recording()
        for e in range(C.N_CHANNELS):
            self.stg.SetElectrodeMode(C.HEADSTAGE, e, N["ElectrodeModeEnumNet"].emAutomatic)
        self.set_blanking(True)
        self.set_mode("voltage")
        A = N["Array"]; U32 = N["UInt32"]
        self.stg.SetupTrigger(0, A[U32]([255]), A[U32]([255]), A[U32]([1]))
        self.dacq.StartDacq()
        print(f"MEA connected. {self.n_streams} streams in block, reading {self.read_streams}.")

    def _setup_recording(self):
        N = self.N
        self.dacq.StopDacq(0)
        N["CSCUFunctionNet"](self.dacq).SetDacqLegacyMode(False)
        self.dacq.SetSamplerate(self.fs, 0, 0)
        self.dacq.SetDataMode(N["DataModeEnumNet"].Signed_32bit, 0)
        self.dacq.SetNumberOfAnalogChannels(60, 0, 0, 8, 0)
        D = N["DigitalDatastreamEnableEnumNet"]
        self.dacq.EnableDigitalIn(D.DigitalIn | D.DigitalOut | D.Hs1SidebandLow | D.Hs1SidebandHigh, 0)
        self.dacq.EnableChecksum(True, 0)
        I32 = N["Int32"]
        _, _, checksum_ch, timestamp_ch, channels_in_block = self.dacq.GetChannelLayout(
            I32(0), I32(0), I32(0), I32(0), I32(0), 0)
        self.n_streams = channels_in_block // 2
        self.read_streams = self.n_streams
        block = self.dacq.ChannelBlock
        block.Init(channels_in_block)
        block.AddBlocksAndChannels(N["ChannelBlockTypeNet"].MultipleHandlesOneQueues,
                                   N["Array"][bool]([True] * self.n_streams), self.fs, self._frames,
                                   N["SampleSizeNet"].SampleSize32Signed, N["SampleDstSizeNet"].SampleDstSize32, 0, 0)
        block.SetCommonThreshold(self._frames)
        block.SetCheckChecksum(checksum_ch, timestamp_ch)

    def _to_numpy(self, net_array, length):
        out = np.empty(length, dtype=np.int32)
        self.N["Marshal"].Copy(net_array, 0, self.N["IntPtr"](out.ctypes.data), length)
        return out

    def _on_data(self, dacq, handle, num_frames):
        cols = []
        nmin = None
        for s in range(self.read_streams):
            try:
                data, n = dacq.ChannelBlock.ReadFramesI32(s, 0, self._frames, self.N["Int32"](0))
            except Exception as e:  # stream not readable -> fall back to analog only
                self.read_error = f"stream {s}: {e}"
                self.read_streams = max(60, s)
                break
            cols.append(self._to_numpy(data, n))
            nmin = n if nmin is None else min(nmin, n)
        if not cols or not nmin:
            return
        chunk = np.stack([c[:nmin] for c in cols])
        with self._lock:
            if self.writer is not None:
                if chunk.shape[0] != self.writer.n_streams:   # stream fallback mid-block: keep file shape
                    fixed = np.zeros((self.writer.n_streams, chunk.shape[1]), np.int32)
                    k = min(chunk.shape[0], self.writer.n_streams)
                    fixed[:k] = chunk[:k]
                    chunk = fixed
                self.writer.push(chunk)

    # ---------------- stimulation config ----------------
    def set_blanking(self, on):
        for e in range(C.N_CHANNELS):
            self.stg.SetEnableAmplifierProtectionSwitch(C.HEADSTAGE, e, False)   # as in mea_device.py
            self.stg.SetBlankingEnable(C.HEADSTAGE, e, bool(on))

    def set_mode(self, mode):
        for g in (0, 1):
            ch = 2 * C.HEADSTAGE + g
            (self.stg.SetCurrentMode if mode == "current" else self.stg.SetVoltageMode)(ch)
        self.mode = mode

    def route(self, assign):
        """assign: {electrode: generator 0/1}. Every other electrode is disabled + grounded.
        Only electrodes whose setting CHANGES are sent over USB (re-sending all 60 would take far too
        long for the 5 ms switching test). Returns the wall time it took (ms)."""
        M = self.N["ElectrodeDacMuxEnumNet"]
        t = time.perf_counter()
        cur = getattr(self, "_assign", None)
        for e in range(C.N_CHANNELS):
            g = assign.get(e)
            if cur is not None and cur.get(e, "off") == (g if g is not None else "off"):
                continue
            if g is None:
                self.stg.SetElectrodeEnable(C.HEADSTAGE, e, 0, False)
                self.stg.SetElectrodeDacMux(C.HEADSTAGE, e, 0, M.Ground)
            else:
                self.stg.SetElectrodeEnable(C.HEADSTAGE, e, 0, True)
                self.stg.SetElectrodeDacMux(C.HEADSTAGE, e, 0, M.Stg1 if g == 0 else M.Stg2)
        self._assign = {e: (assign[e] if e in assign else "off") for e in range(C.N_CHANNELS)}
        return (time.perf_counter() - t) * 1000

    def send(self, trains, window_ms):
        """trains: {generator: (amps, durs_us, active)}; missing generators get silence.
        Returns (sample index in the current block when SendStart was called, ms spent sending)."""
        N = self.N; A = N["Array"]
        dest = N["STG_DestinationEnumNet"].channeldata_current if self.mode == "current" else N["STG_DestinationEnumNet"].channeldata_voltage
        t = time.perf_counter()
        for g in (0, 1):
            amps, durs, active = trains.get(g, silent(window_ms))
            ch = 2 * C.HEADSTAGE + g
            amp = A[N["Int32"]]([int(a) for a in amps])
            dur = A[N["UInt64"]]([int(d) for d in durs])
            sb = self.stg.Stimulus.CreateSideband(A[N["Int32"]]([int(x) for x in active]),
                                                  A[N["Int32"]]([0] * len(active)), dur, *C.SIDEBAND_TIMES)
            self.stg.PrepareAndSendData(ch, amp, dur, dest)
            self.stg.PrepareAndSendData(ch, sb.Sideband, sb.Duration, N["STG_DestinationEnumNet"].syncoutdata)
        sample = self.writer.samples if self.writer is not None else 0
        self.stg.SendStart(1)
        return sample, (time.perf_counter() - t) * 1000

    def wait_ms(self, ms):
        time.sleep(ms / 1000.0)

    # ---------------- blocks ----------------
    def start_block(self, prefix, meta):
        with self._lock:
            self.writer = RawBlockWriter(prefix, self.fs, self.read_streams, meta)

    def stop_block(self, extra_meta=None):
        time.sleep(0.1)  # let the last chunk arrive
        with self._lock:
            w, self.writer = self.writer, None
        extra = dict(extra_meta or {})
        extra.update({"read_streams": self.read_streams, "n_streams_in_block": self.n_streams, "read_error": self.read_error})
        return w.close(extra)

    def close(self):
        if self.dacq is not None:
            self.dacq.StopDacq(0)
            self.dacq.Disconnect()
        if self.stg is not None:
            self.stg.Disconnect()
        print("MEA disconnected.")
