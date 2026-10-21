"""
Run this FIRST on the lab PC. No stimulation. Abbas, Oct 21 2026 (new).

    python -m mea_kit.hardware.probe_api                 # DLL only: does it have every call we use?
    python -m mea_kit.hardware.probe_api --connect       # + talk to the MEA: ranges, streams, 2 s of data

Writes probe_report.txt next to where you run it. Checks:
  * every McsUsbNet.dll call that device_mcs.py uses exists (with its parameter names)
  * CMcsUsbBStimNet / SetStimulationPattern are NOT in the DLL (so code that imports them, like the old
    Hardware-Pythonnet-Path interface and Abbas_mea_device.py, cannot run)
  * with --connect: stimulator voltage/current ranges per generator (are current units nA?),
    number of streams in a data block, which streams change during 2 s of recording (analog vs digital),
    and whether ReadFramesI32 works on the non-analog (sideband) streams
"""
import argparse
import sys
import time

REQUIRED = {
    "CStg200xDownloadNet": ["Connect", "Disconnect", "SetElectrodeMode", "SetElectrodeEnable", "SetElectrodeDacMux",
                            "SetBlankingEnable", "SetEnableAmplifierProtectionSwitch", "SetVoltageMode", "SetCurrentMode",
                            "SetupTrigger", "PrepareAndSendData", "SendStart", "SendStop", "get_Stimulus",
                            "GetVoltageRangeInMicroVolt", "GetCurrentRangeInNanoAmp", "SetListmodeIndexRange", "ListModeSendStart"],
    "CMeaUSBDeviceNet": ["Connect", "Disconnect", "StartDacq", "StopDacq", "SetSamplerate", "SetDataMode",
                         "SetNumberOfAnalogChannels", "EnableDigitalIn", "EnableChecksum", "GetChannelLayout"],
}
MUST_NOT_EXIST = ["CMcsUsbBStimNet"]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dll", default=None)
    ap.add_argument("--connect", action="store_true")
    args = ap.parse_args(argv)
    lines = []

    def say(s=""):
        print(s)
        lines.append(str(s))

    import clr
    from .device_mcs import default_dll_path
    dll = args.dll or str(default_dll_path())
    clr.AddReference(dll)
    import Mcs.Usb as M
    say(f"DLL: {dll}")
    ok = True
    for cls, methods in REQUIRED.items():
        t = clr.GetClrType(getattr(M, cls))
        have = {}
        for m in t.GetMethods():
            have.setdefault(m.Name, []).append("(" + ", ".join(f"{p.ParameterType.Name} {p.Name}" for p in m.GetParameters()) + ")")
        for p in t.GetProperties():
            have.setdefault("get_" + p.Name, ["property"])
        for name in methods:
            if name in have:
                say(f"  OK   {cls}.{name}  {' | '.join(have[name][:3])}")
            else:
                ok = False
                say(f"  MISSING  {cls}.{name}")
    for name in MUST_NOT_EXIST:
        say(f"  {'PRESENT (unexpected)' if hasattr(M, name) else 'absent (expected)'}: {name}")
    say(f"STG_DestinationEnumNet: {[str(x) for x in __import__('System').Enum.GetNames(clr.GetClrType(M.STG_DestinationEnumNet))]}")
    say("All required calls present." if ok else "SOME CALLS MISSING - do not run the protocol; send this report.")
    if args.connect:
        import numpy as np
        from .device_mcs import MCSDevice
        dev = MCSDevice(dll_path=dll)
        dev.connect()
        try:
            for g in (0, 1):
                ch = 2 * 0 + g
                for fn in ("GetVoltageRangeInMicroVolt", "GetCurrentRangeInNanoAmp"):
                    try:
                        say(f"  generator {g + 1}: {fn}({ch}) = {getattr(dev.stg, fn)(ch)}")
                    except Exception as e:  # noqa: BLE001
                        say(f"  generator {g + 1}: {fn} failed: {e}")
            for fn in ("GetNumberOfStimulationElectrodes", "GetNumberOfStimulationSourcesPerElectrode", "GetTotalMemory"):
                try:
                    say(f"  {fn}() = {getattr(dev.stg, fn)()}")
                except Exception as e:  # noqa: BLE001
                    say(f"  {fn} failed: {e}")
            say(f"  streams in data block: {dev.n_streams} (analog expected 60)")
            import tempfile, os
            tmp = os.path.join(tempfile.gettempdir(), "probe_block")
            dev.start_block(tmp, {"probe": True})
            time.sleep(2.0)
            m = dev.stop_block()
            say(f"  recorded {m['n_samples']} samples x {m['n_streams']} streams in 2 s (read_error={m.get('read_error')})")
            raw = np.fromfile(tmp + ".bin", dtype=np.int32).reshape(-1, m["n_streams"])
            sd = raw.std(axis=0)
            say(f"  analog streams 0-59 std (counts): min {sd[:60].min():.1f}, median {np.median(sd[:60]):.1f}, max {sd[:60].max():.1f}")
            if m["n_streams"] > 60:
                say(f"  extra streams 60+: std {np.round(sd[60:], 1).tolist()}  (a sideband stream shows activity only while stimulating)")
            flat = [int(c) for c in np.flatnonzero(sd[:60] < 0.1 * np.median(sd[:60]))]
            say(f"  flat analog channels: {flat or 'none'}")
        finally:
            dev.close()
    with open("probe_report.txt", "w") as f:
        f.write("\n".join(lines) + "\n")
    print("Saved probe_report.txt")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
