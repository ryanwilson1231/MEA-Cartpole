# Saline-Test: artifact removal, saline benchmark, and UCSC-style mapping

*Abbas, Oct 21, 2026. Built for the Oct 22 saline test on the MEA2100-Mini-60.*

- **For the test:** [`TOMORROW_TEST_LIST.md`](TOMORROW_TEST_LIST.md), step by step
- **What changed and why:** [`CHANGES_abbas_2026-10-21.md`](CHANGES_abbas_2026-10-21.md)

## The packages (each usable on its own)

| Package | Use it for | Run |
|---------|-----------|-----|
| `mea_kit/artifact_removal` | Cleaning stimulation artifacts. SALPA, simple blanking, template subtraction and SpikeInterface share one call: `get_remover("salpa").clean_channel(x, fs, pulse_samples)` | library |
| `mea_kit/saline_benchmark` | Scoring every remover × stimulation strategy on a saline recording. Outputs the pivot table. | `python -m mea_kit.saline_benchmark.run_benchmark --session S` |
| `mea_kit/ucsc_mapping` | UCSC network mapping: v1 as-is, v2 adapted to our rig, v3 automatic role selection, plus drift | `python -m mea_kit.ucsc_mapping.run_mapping --session S --version all` |
| `mea_kit/hardware` | Saline stimulation protocol for the lab PC (pythonnet + `McsUsbNet.dll`), a hardware probe, and a fake device for dry runs | `python -m mea_kit.hardware.probe_api` / `python -m mea_kit.hardware.saline_protocol --out S [--dry-run]` |

## Install

```
pip install -r requirements.txt          # numpy scipy matplotlib h5py salpa spikeinterface pytest
pip install pythonnet                    # lab PC (Windows) only
python -m pytest -q tests                # should say 22 passed
```

Run from this folder (`Saline-Test/`), or put it on `PYTHONPATH`. The hardware code finds the DLL at `Baseline-Protocol/Hardware/McsUsbNet.dll` by itself.

## The pivot table

**Rows** are stimulation strategies. All use cathodic-first biphasic pulses:

| Row | Strategy |
|-----|----------|
| R1 | Normal stim: today's 75 mV, 200 µs/phase voltage pulse |
| R2 | Current-mode, 10 µA, 200 µs/phase |
| R3 | Short stim: current-mode, 10 µA, 100 µs/phase |
| R4 | Optional: hardware blanking OFF, to show how much blanking helps |
| R5 | Moved decoder zones: 2 input electrodes per side, decoder zones away from them |

Rows R1–R3 and R5 keep hardware blanking ON, as `mea_device.py` does. So every SALPA cell in those rows is "hardware blanking + SALPA removes the leftover".

**Columns:** SALPA · Simple blanking · Template subtraction · SpikeInterface, with No cleaning as the reference.

**Cells** hold one table per metric:

| Metric | What it measures | Good on saline |
|--------|------------------|----------------|
| Blind period | Syrine's "measure the blind period". Measured for every cell, not one row. | Short |
| False spikes | Spikes detected after pulses | Close to 0 |
| Recovery of injected fake spikes | Saline can't show whether a remover eats real spikes; this can. | High |
| Decoder bias | The game's own `count_spikes` picking the stimulated side | 50% |

The **Verdict** table colours each cell PASS / CHECK / FAIL.

## Things to know

- **Fake data.** Dry-run results come from a simulated device whose artifact shape is a guess. They prove the code runs, not which method wins. Only the real saline data ranks the methods.
- **Template subtraction will look better on saline than on cells.** The artifact shape repeats exactly in saline; with neurons, responses ride on the tail.
- **SALPA's interface differs from Syrine's notes.** The pip package's `params()` / `run(in_file, out_file)` API doesn't work. The kit uses the working in-memory call `salpa(data, tau, ...)`, so no raw-file export is needed. The kit also sets SALPA's "pegged" time from the measured hardware-blanking hold, because otherwise SALPA leaves a fake spike where the hold releases.
- **Any blanking remover needs a matching decoder change.** The decoder must ignore the blanked samples (`masked_count_spikes`), or the edges of the blank look like spikes. The table reports both the masked decoder and the as-is decoder.
- **Disk.** All streams at 50 kHz is about 13 MB/s. The full protocol is about 7 GB.
