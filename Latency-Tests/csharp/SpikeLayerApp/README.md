# SpikeLayerApp: the C# spike server

Plays stimulation waves on the MEA, records continuously, counts spikes per
electrode and sends them back to the Python game loop over TCP.

Windows rig only: McsUsbNet.dll is a Windows .NET Framework library. The code
compiles on a Mac, but it only runs on the rig.

## Run

```
dotnet build -c Release
SpikeLayerApp.exe --serve            # spike server on 127.0.0.1:5005 (Ctrl+C to stop)
SpikeLayerApp.exe --save NAME --seconds 60   # record to sessions/NAME.bin + .json, no game
SpikeLayerApp.exe --minutes 10       # 10-minute recording check, prints PASS/FAIL
SpikeLayerApp.exe [--stim]           # Ryan's latency test (record-only, + round trip)
```

If Windows refuses to load the DLL, run `Unblock-File McsUsbNet.dll` in the
output folder.

From Python:

```python
import spike_client
spike_client.start_session("2026-11-10_saline_01")
first_sample, counts = spike_client.play_and_read(1, left_wave, right_wave)
```

A wave is a list of `(amplitude_uV, length_us)` pieces. `[]` = that half stays silent.

## Protocol (little-endian)

| Direction | Format | Contents |
|---|---|---|
| Python → C# | `<4sI` + name | `b"SESS"`, name length, name as UTF-8 |
| Python → C# | `<4sIII` + pairs | `b"WAVE"`, window, left count, right count, then `<iI` (amplitude µV, length µs) pairs, left first |
| C# → Python | `<4sIQI60i` (260 B) | `b"SPKS"`, window, first sample of the window in the `.bin`, 60, 60 counts |

The server **refuses** a wave (doesn't play it, prints why and closes the
connection) if any piece is over 300 mV, has a length that isn't a positive
multiple of 20 µs, or the wave is longer than 11 s. It also refuses a WAVE
before SESS, and won't overwrite an existing session.

## Files

Same format as Abbas's Python recorder (`Saline-Test/mea_kit/hardware/recorder.py`
on the Abbas-changes branch), so its `load_recording()` opens them directly.

`sessions/<name>.bin`: raw AD counts, int32 little-endian, sample-major (for
each sample, channels 0-59). `sessions/<name>.json`: `fs`, `n_streams`,
`analog_streams`, `uv_per_count` (multiply counts by this for µV) and, once the
session closes, `n_samples` and every window (first sample, length, both waves,
the 60 counts). The .json is written when the session starts too, so even a
crashed session can be opened.

Check a file (this is the "60-second file opens and plots" check):

```
python check_recording.py sessions/NAME      # prints OK/PROBLEMS, saves sessions/NAME.png
```

It needs `Saline-Test/mea_kit/common/recording.py`; if it's not in your checkout:
`git checkout origin/Abbas-changes -- Saline-Test/mea_kit`.

Without mea_kit:

```python
raw = np.fromfile("sessions/x.bin", dtype="<i4").reshape(-1, 60)
uv = raw * json.load(open("sessions/x.json"))["uv_per_count"]
```

## Spike counting (`SpikeCounter.cs`)

Per electrode, over the window plus 10 ms margins on each side:
1. Bridge every masked stretch (each pulse until 2 ms after it, on either half) with a straight line.
2. Band-pass 300–3000 Hz, forwards and backwards.
3. Noise = median(|x|) / 0.6745 over the unmasked window.
4. Count downward crossings of −5 × noise. Skip masked samples, and anything within 1 ms of the last spike.

Step 1 matters: without it, the backwards filter pass spreads each artifact
up to 4 ms *before* the pulse. On fake data, that added 2–3 false spikes per
pulse on every electrode.

## Known limitations

- **Window timing is an estimate.** The window's first sample is "frames
  received + frames waiting in the DLL queue" at the moment `SendStart`
  returns. It doesn't include the USB transfer delay or the stimulator's own
  start-up time. The fix is to read the stimulator's timing stream from the
  recording (Round-1 T3 fix 5). Measure the offset on saline first.
- **The 2 ms mask is a placeholder.** Tune it after saline (`MASK_AFTER_US`).
- **Noise is re-estimated in every window.** T5 fix 3 says to calibrate it
  once per session instead.
- **300 mV is the limit requested for the server.** T4 fix 5 suggests 150 mV.
- **The µV factor is unconfirmed** until the first powered run. Check the
  `GetResolutionPerDigit` line at startup.
