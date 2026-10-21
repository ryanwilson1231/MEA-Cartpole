"""
Hardware side of the saline test. Abbas, Oct 21 2026 (new).

  config.py          the pivot-table rows (stimulation conditions) + protocol sizes + safety limits
  stim_pulses.py     builds cathodic-first (negative-first) biphasic pulse trains, checks charge limits
  recorder.py        writes EVERY stream (60 analog + digital/sideband) to disk as it arrives
  device_mcs.py      the real MEA2100-Mini (pythonnet + McsUsbNet.dll), Windows lab PC only
  device_fake.py     same interface, simulated saline + artifacts, so everything runs anywhere (--dry-run)
  probe_api.py       run FIRST on the lab PC: lists the DLL calls we rely on + device ranges, no stimulation
  saline_protocol.py runs the test blocks and writes one folder per session
"""
