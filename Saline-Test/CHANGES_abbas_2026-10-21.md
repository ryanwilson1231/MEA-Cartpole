# Changes: Abbas, Oct 21, 2026

**Branch:** `abbas/2026-10-21-saline-kit`
**Folder added:** `Saline-Test/`
**Existing files changed:** none. `Baseline-Protocol/` and the game code are untouched.

## Why

We test on saline on Oct 22. Before any live culture we need to know:

1. how long each stimulation pulse blinds the electrodes
2. which artifact remover gets the signal back best
3. whether the artifact can steer the game's decoder
4. whether the UCSC mapping method works on our 60-electrode rig

Saline has no neurons, so all of these have a known right answer.

## What was added

| Package | What | Why |
|---------|------|-----|
| `mea_kit/artifact_removal/` | 4 removers with one shared interface: SALPA, simple blanking (3 ms, from my old `STIM_BLANK_MS` idea), template subtraction, SpikeInterface `remove_artifacts`. Plus `none` as the reference, and a pure-Python SALPA-like fallback in case `salpa` won't install. | These are the pivot-table columns. Each can be tested alone. |
| `mea_kit/saline_benchmark/` | Scores every (stimulation row × remover) cell: blind period, false spikes, recovery of injected fake spikes, and decoder bias using the game's own `count_spikes`. Writes a colour-coded HTML pivot, CSVs and Markdown. | This is the benchmark for the saline test. |
| `mea_kit/ucsc_mapping/` | v1, UCSC as-is (5×RMS units, footprint merge, top-32 by η, 3 SD responses, C1 10/18 ms, Cm 200 ms, median+3MAD bursts, rubric roles). v2, adapted to our rig (electrode = unit, baseline-corrected C1 + exact test + FDR, both windows, starts after the blind period). v3, automatic input/zone selection. Drift comparison. | Syrine's plan, steps 1–2. Saline is the null test for it. |
| `mea_kit/hardware/` | Saline protocol: baseline, rows R1–R5, sweep, amplitude series, switching test. Pulses are cathodic-first. Every stream is recorded to disk. Includes a fake device for dry runs and `probe_api.py`, which checks the DLL with no stimulation. | Produces the data the benchmark needs, in one command. |
| `tests/` | 22 tests (incl. "blanking stays ON"): interface, removal, pulse timing with and without the sideband, end-to-end dry run, mapping recovers known connections, safety limits. | So it's known to run before tomorrow. |
| `archive/abbas_2026-10-21_old_mea_device.py` | My old `Abbas_mea_device.py`, moved out of the repo root (it was untracked, not actually in `Baseline-Protocol/Hardware/` as planned) and archived with a header explaining why it's unused. | Can't run - imports `CMcsUsbBStimNet`, which isn't in our DLL (finding 8). Its two ideas live on elsewhere; see the header. |
| Root `.gitignore`, root `README.md` | Added `sessions/`, `*.bin`, `probe_report.txt` to the root `.gitignore`; added a `Saline-Test/` row to the root README's repo layout table. | Recordings are ~7 GB and must never be committed; new members should see the kit in the repo layout. |

## Evidence

All of the evidence below comes from a fake device and fake data, so it shows the code paths work, not which method is best:

- `pytest`: 22 passed.
- **Dry run end to end** (simulated device → files → benchmark → mapping): runs.
- **Pulse times recovered exactly** from the sideband stream.
- **Pulse timing without the sideband:** artifact-based fallback, within 2 samples (median).
- **Mapping on a simulated culture with 10 known connections:** v2 found 10/10 with 0 false; v1 (UCSC as-is) reported 46.
- **Fake saline (no neurons):** v1 reported 377 fake "connections"; v2 found 0 significant pairs out of 708.
- Every DLL call used by `device_mcs.py` was checked against the `McsUsbNet.dll` type list. All three copies of the DLL in the repo are identical.
- **Not yet run on real hardware.**

## Findings in the existing code (for later, list #4: hardware and simulation issues)

1. **The decoder can be steered by artifact (most important).** `run_hardware.py` stimulates the side the pole leans toward and decodes spikes from that same window. Artifact on the stimulated side → that side wins → the cart is pushed toward the lean, which is CartPole's balancing heuristic. So artifact alone could fake learning. Tomorrow's step 4 tests it.
2. `mea_device.py` pulses are **anodic-first** (`+A` then `-A`). We agreed on cathodic-first.
3. `mea_device.py` calls `SetVoltageMode(0)`. That looks like it sets only channel 0 (generator 1). The kit sets both channels. Check with the probe.
4. `count_spikes` estimates noise inside the same 100 ms window that holds the artifact. Any blanking cleaner needs the decoder to ignore blanked samples (`masked_count_spikes`), or the blank edges count as spikes. The dry run showed this.
5. `read_spike_counts` clears the buffer and then sleeps, so the 100 ms window isn't aligned to the pulse. USB/chunk latency is several ms.
6. Only the 60 analog streams are read in the game. The sideband (exact pulse times) is never saved.
7. The code assumes stim electrode k = recording channel k (`LEFT_CHANNELS` is used for both). The sweep tests this.
8. `Hardware-Pythonnet-Path/` and my old `Abbas_mea_device.py` import `CMcsUsbBStimNet` / `SetStimulationPattern`. **These don't exist in our DLL**, so that code can't run. Also, `square.py` treats a duration in ms as seconds, and `spike.py` assumes a 1 s time axis for a 50 ms buffer, so its filters are 20× off. `Baseline-Protocol/` replaces both.
9. **Simulation:** the Brian2 sim has no artifact model, so it can't show problem 1. Later, add the saline-measured artifact to it.

## Decisions

- **Pulse polarity.** All new stimulation is cathodic-first biphasic.
- **Current mode.** Rows R2, R3 and R5 use current mode. R1 keeps today's voltage pulse (made cathodic-first) as the reference.
- **Hardware blanking.** Stays ON except optional row R4.
- **Old file.** `Abbas_mea_device.py` is removed from `Baseline-Protocol/Hardware/` and archived in `Saline-Test/archive/`. Both of its ideas live on: the 3 ms software blank is `blank_clean.py`, and the hardware blanking via `CStg200xDownloadNet` is already in `mea_device.py`. It can't run anyway (see finding 8).

## Open questions

| Question | Who |
|----------|-----|
| Safe current amplitude and charge per phase for our electrodes (10 or 30 µm)? | Kai / lab lead |
| OK to turn hardware blanking OFF on saline (row R4)? | Kai |
| What does `SetEnableAmplifierProtectionSwitch(False)` mean for us? | Kai |
| What do the sideband times `(40, 800, 40)` mean, and is 800 µs the blanking length? | Kai / MCS docs |
| List mode (`SetListmodeIndexRange` / `ListModeSendStart`) may allow hardware-timed electrode switching, which would beat USB re-routing for the 5 ms question. Untested. | Abbas / Kai |
