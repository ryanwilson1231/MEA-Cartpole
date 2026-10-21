# Saline test: Oct 22, 2026 test list

*Abbas, written Oct 21, 2026. Print this or keep it open at the rig.*

The goal is to find which artifact-removal approaches are worth pursuing before any live culture. Saline has **no neurons**, so the right answer is always known:

- zero real spikes
- 0 significant connections
- the decoder picks either side 50% of the time

Anything else is artifact.

Total time at the rig is about 45 minutes. Disk needed is about **7 GB** (all streams at 50 kHz).

## 0. Before the rig (lab PC, no MEA needed, 5 min)

| # | Do | Pass if |
|---|----|---------|
| 0a | `pip install -r Saline-Test/requirements.txt` (plus `pythonnet` on the lab PC) | Installs. If `salpa` fails, the kit swaps in a pure-Python stand-in automatically. |
| 0b | `python -m pytest -q Saline-Test/tests` | All tests pass. |
| 0c | `python -m mea_kit.hardware.saline_protocol --dry-run --out sessions/dry --game-windows 30 --sweep-electrodes 0-3` | Session folder is written. |
| 0d | `python -m mea_kit.saline_benchmark.run_benchmark --session sessions/dry` | `sessions/dry/benchmark/report.html` opens. |

## 1. Probe the hardware (MEA plugged in, no stimulation, 5 min)

| # | Do | Pass if / what to note |
|---|----|---------|
| 1a | `python -m mea_kit.hardware.probe_api` | "All required calls present." The report also shows `CMcsUsbBStimNet` as absent. |
| 1b | `python -m mea_kit.hardware.probe_api --connect` | Note four things: the **current range** for each generator (should be in nA, around 1,000,000 = 1 mA), the **number of streams**, which extra streams exist, and whether any analog channel is flat. |
| 1c | Ask **Kai**: are the amplitudes OK? Is it OK to turn blanking OFF (row R4)? What does `SetEnableAmplifierProtectionSwitch(False)` in mea_device.py mean? | Answers written down. |

## 2. Saline setup (10 min)

1. Fill the MEA with saline or PBS, fit the reference electrode, and switch on the headstage.
2. Wait **5–10 minutes** so the electrodes settle. Electrodes drift for the first minutes in liquid.
3. Write down: saline type and volume, MEA type and electrode diameter (10 or 30 µm), temperature, and the time.

## 3. Run the protocol (about 10 min of recording)

```
python -m mea_kit.hardware.saline_protocol --out sessions/2026-10-22_saline --notes "PBS, 60MEA200/30, room temp"
```

Add `--include-blanking-off` **only if Kai said yes**.

Blocks, in order:

| Block | What it is | Answers |
|-------|------------|---------|
| baseline | 60 s, no stimulation | Noise floor, and whether all 60 channels are alive (Syrine's step 3). |
| R1_normal | Game-style, voltage 75 mV, 200 µs/phase, cathodic-first | Pivot row 1. |
| R2_current | Game-style, current 10 µA, 200 µs/phase | Pivot row 2. |
| R3_short | Game-style, current 10 µA, 100 µs/phase | Pivot row 3 ("short stim"). |
| R4_blanking_off | Optional, hardware blanking OFF | Pivot row 4: how much hardware blanking helps. |
| R5_moved_zones | 2 input electrodes per side, decoder zones away from them | Pivot row 5. |
| sweep | One electrode at a time, 10 pulses at 2 Hz each | Electrode map (is stim electrode k = recording channel k?) and the UCSC null map. |
| amp_series | Electrode 12 at 5, 10 and 20 µA | Artifact size and blind period vs amplitude. |
| switch | One generator re-routed every 5, 10 or 20 ms, vs two generators alternating | Syrine's open question: can a generator switch electrodes every 5 ms? |

If anything looks wrong, Ctrl+C. The blocks that already finished are saved.

## 4. Play the actual game on saline (5 min)

```
cd Baseline-Protocol/Hardware && python run_hardware.py      (set EPISODES = 20)
```

Copy `episode_lengths.csv` into the session folder. With no neurons, the episodes should average about **22 steps** (random play).

**If it clearly beats random (above about 30), the artifact is playing the game.** The game stimulates the side the pole leans toward and decodes from that same side while the stimulation plays. Pushing toward the lean side is the simple strategy that balances CartPole, so artifact alone would fake learning.

## 5. Analyse (laptop, about 15 min of compute)

```
python -m mea_kit.saline_benchmark.run_benchmark --session sessions/2026-10-22_saline --episodes sessions/2026-10-22_saline/episode_lengths.csv
python -m mea_kit.ucsc_mapping.run_mapping --session sessions/2026-10-22_saline --version all
```

Open `benchmark/report.html`. It holds the pivot tables:

- **rows** = stimulation strategies
- **columns** = SALPA / Simple blanking / Template / SpikeInterface (plus No cleaning as the reference)

| Check | Good result on saline |
|-------|-----------------------|
| Table 1: Verdict | At least one PASS per row you care about |
| Tables 2–3: Blind period (Syrine's "measure the blind period") | Short. 2 ms or less is great; 5 ms or more is a problem for C1's 10 ms window. |
| Table 4: False spikes | Close to 0 per 100 pulses |
| Tables 5–6: Injected spike recovery (2–10 ms) | 85% or more. Template will look too good on saline. |
| Table 7: Decoder picks the stimulated side | About 50% (the 95% CI includes 50%) |
| Table 8: Decoder as-is | The same, using today's `count_spikes` unchanged |
| Electrode map | "matches" (identity at 90% or more). If not, the game decodes different electrodes than it stimulates. |
| Mapping v2 null test | **0 significant pairs.** v1 will show fake ones, and that is expected. |
| Switch test | "right electrode, in order" near 100% at the target gap. That is your answer for 5 ms. |
| Game on saline | About 22 steps |

## 6. Decide (write it in the checkpoint, Section 3)

- Which remover goes into the game: the best PASS in the row matching the stimulation we'll use.
- Current mode vs voltage, and normal vs short pulses: compare rows R1–R3.
- Keep the half-array stimulation, or move to separate input and decoder zones (R5)?
- 5 ms switching: yes or no. If no, use two alternating generators, or space training pulses about 20 ms apart.
- Anything for Kai or Syrine (the open questions in CHANGES_abbas_2026-10-21.md).
