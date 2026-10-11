# System Overview

What the project is, what the hardware is, how one game step flows through it, and where each part lives in the code. For known
problems, see `Pipeline-Review.md`.

## The project in one paragraph

Living neurons grown on a **microelectrode array (MEA)**, a dish with 60 tiny electrodes in its floor, play the CartPole game. Every
game step, we **stimulate** some electrodes to tell the neurons which way the pole is leaning, **record** the neurons' electrical spikes on
all 60 electrodes, and turn "more spikes on the left half" or "more on the right half" into pushing the cart left or right. The idea comes
from DishBrain (Kagan et al., 2022), where cultured neurons learned to play Pong this way (`References/`).

## The hardware

An **MCS MEA2100-Mini-System**, connected to a Windows computer (currently Ryan's laptop) (manual pp. 6–9):

```
 ┌──────────────────────────┐   cable (3 m)   ┌──────────────────────┐   iX cable   ┌────────────────────────┐   USB-C   ┌──────────────────┐
 │ Headstage MEA2100-Mini   │ ───────────────▶│ Signal Collector     │ ────────────▶│ Interface Board IFB-C  │ ─────────▶│ Windows computer  │
 │ - holds the MEA          │                 │ Unit (SCU)           │              │ - USB to the computer  │  (USB 3,  │ - Python + DLL    │
 │ - 60 amplifiers + ADC    │                 │ - inputs HS1–HS4     │              │ - digital/analog I/O   │  no hub)  │ - Multi Channel   │
 │ - 2 stimulus generators  │                 │ - 4 LED outputs for  │              │ - power (24 V)         │           │   Suite (driver)  │
 │ - blanking circuit       │                 │   optical stimulation│              │                        │           │                   │
 │ - can sit in incubator   │                 └──────────────────────┘              └────────────────────────┘           └──────────────────┘
 └──────────────────────────┘
```

What can go in the headstage:

| Item | What it is | What it's for |
|---|---|---|
| **Test model probe "Test-60MEA"** | A dummy MEA: each of the 60 "electrodes" is a 220 kΩ resistor plus a 1 nF capacitor to ground (manual p. 13) | Checking electronics, noise, stimulator routing and channel numbering. No electrochemistry, no neurons. |
| **Saline / media-only MEA** | A real MEA with real electrodes, filled with liquid, no cells | Later rounds: measures stimulation artifacts on real electrodes with no neurons. DishBrain used "media-only" MEAs as a control group. |
| **MEA with a culture** | The real experiment | Later rounds, once the code has passed the hardware tests. |
| Signal Generator 60MEA2100-SG (optional accessory) | Plays known test signals into the headstage (manual p. 14) | Would be ideal for testing spike detection with known spikes. Check if the lab has one. |

**Key specs (manual p. 21)**

| | |
|---|---|
| Recording channels | 60 |
| Resolution / input range | 24 bit / ±70 mV |
| Sampling rate | up to 50 kHz per channel (we use 50 kHz) |
| Hardware bandwidth | DC to 10 kHz, set in software (Bessel filters, MCS Filter Configuration program) |
| Input noise | typically 0.7 µV RMS; about 20 µV peak-to-peak on the test probe (p. 11) |
| Stimulus generators | 2 per headstage, independent; current (±1 mA) or voltage (±10 V) mode |
| Stimulator resolution | 16 bit, 20 µs time steps |
| Blanking | disconnects electrodes from amplifiers during stimulation; "reduces" artifacts (p. 7) |

**Settings specific to our setup.** Filled in on the test days (`Test-Day-Run-Sheet.md`).

| Setting | Value | How to find it |
|---|---|---|
| SCU port the headstage is on (HS1–HS4) → `HEADSTAGE` | _?_ | Look at the SCU front panel. HS1 = 0 … HS4 = 3. |
| MEA type (layout, reference electrode) | _?_ | Ask the wet-lab group; MCS datasheet |
| Hardware filter (high-pass / low-pass) | _?_ | MCS Filter Configuration program |
| Data stream index of the stimulator timing stream | _?_ | Test day, check 3: the stream that changes when the stimulator fires |
| Recording channel ↔ stimulator electrode index map | _?_ | Test day, check 4 (needs the test probe): `channel_map.py` |
| Amplifier protection switch decision | _?_ | MCS support's answer, or a comparison on the hardware |
| Test-60MEA test probe in the kit? | _?_ | Check the hardware kit (Kai) |
| Python / pythonnet / Multi Channel Suite versions | _?_ | `Baseline-Protocol/Hardware/SETUP-WINDOWS.md` (Ryan) |

## One full cycle (Baseline-Protocol/Hardware)

**Setup, once:** `run_hardware.py` creates CartPole and `MEADevice`, then `connect()`:
1. Finds the device over USB and opens it twice: once for recording (`CMeaUSBDeviceNet`) and once for the stimulator
   (`CStg200xDownloadNet`).
2. Recording: 50 kHz, 60 electrodes, 32-bit samples. The DLL calls `_on_data` every 20 ms with a 1,000-sample chunk per electrode,
   on its own thread; chunks go into a list.
3. Stimulator: electrodes 0–29 are wired to generator 1 ("left") and 30–59 to generator 2 ("right"); blanking on; voltage mode;
   trigger 1 set up to start both generators.

**Each game step (about 100 ms plus overhead):**

| # | What happens | Where |
|---|---|---|
| 1 | Read the pole angle `observation[2]` (radians; positive = leaning right). | `run_hardware.py` |
| 2 | Pick the feedback. If abs(angle) < 0.15 rad: **predictable** (two 75 mV biphasic pulses, 200 µs per phase, 50 ms apart, on the side the pole leans toward; other side silent). Otherwise **unpredictable** (two pulses at random times on *both* sides). | `feedback.is_balanced`, `lean_side` |
| 3 | Build each generator's pulse list (amplitude and duration segments), plus the timing bits that switch electrodes and blanking, upload both with `PrepareAndSendData`, and start with `SendStart(1)`. | `mea_device._pulse_train`, `_send` |
| 4 | Listen: empty the chunk list, wait 100 ms, take 5,000 samples per electrode. | `mea_device.read_spike_counts` |
| 5 | Count spikes per electrode: band-pass 300–3000 Hz, noise = median(abs) / 0.6745, count dips below −5 × noise. | `mea_device.count_spikes` |
| 6 | Decide: total spikes on electrodes 0–29 vs 30–59. More left → push left (0), more right → push right (1), tie → coin flip. | `feedback.choose_action` |
| 7 | `env.step(action)`. The episode ends when the pole passes 0.2095 rad (12°), the cart leaves the track, or 500 steps. | `run_hardware.py` |

**End of an episode:** the length is recorded and the next episode starts immediately (no feedback for failing).
**End of the run:** after 20 episodes, the device closes, `episode_lengths.csv` is saved, and a plot is shown.

**The wiring is a reflex.** If the stimulated side responds more, the cart gets pushed toward the lean, which is the correct move. See
`Pipeline-Review.md` P14 and P19 for why that matters.

**The next design (layout v2), built in round 1 as an option:** stimulation goes in on the bottom row of electrodes (pole leaning left →
left three, leaning right → right three; pulse rate set by angular velocity), and the action is read from the top row (left three vs right
three). Input and output electrodes are separate, so the neurons have to carry the signal across the dish. Details in
`Round-1-Tasks/T1-coordination-and-repo.md`.

## How to read episode lengths

From `Evidence/offline_checks.py` (CartPole-v1, 400 episodes per row):

| What the decisions look like | Average steps |
|---|---|
| Always the same direction (decoder stuck) | ≈ 9 |
| Coin flip (no usable signal, e.g. no cells and no artifacts) | ≈ 22 |
| Push toward the lean 60% of the time | ≈ 30 |
| Push toward the lean 75% of the time | ≈ 41 |
| Push toward the lean every time | ≈ 43 |

## Code map

| File | Role |
|---|---|
Today:

| File | Role |
|---|---|
| `Baseline-Protocol/Hardware/run_hardware.py` | Game loop |
| `Baseline-Protocol/Hardware/feedback.py` | Rules: balance limit, lean side, decoding |
| `Baseline-Protocol/Hardware/mea_device.py` | Device control: setup, recording, spike counting, stimulation |
| `Baseline-Protocol/Hardware/McsUsbNet.dll` | MCS's .NET library (64-bit, .NET Framework 4, Windows only) |
| `Baseline-Protocol/Brian2/` | Simulated version (out of scope for now) |
| `Hardware-Pythonnet-Path/`, root `spike.py`, `square.py`, `Brian2-Path/` | Older code that doesn't run; moving to `archive/` in round 1 (P23) |

Added during round 1 (all in `Baseline-Protocol/Hardware/`):

| File | Role | Built by |
|---|---|---|
| `recording.py`, `stimulation.py`, `spike_detection.py` | `mea_device.py` split into three, so people can work in parallel | Kai, then roles 3, 4, 5 |
| `config.py` | Every setting in one place, saved with each run | Ryan |
| `channel_map.py` | Which electrode is which, for both stimulation and recording | Role 4 |
| `layouts.py` | Encoding/decoding rules: today's baseline and layout v2 | Kai |
| `fake_mea_device.py`, `tests/` | Fake MEA for laptops, automatic tests | Role 6 |
| `session_logger.py`, `../../analysis/session_report.ipynb` | Session logs and the report | Role 7 |
| `SETUP-WINDOWS.md` | How to set up the Windows computer | Ryan |
