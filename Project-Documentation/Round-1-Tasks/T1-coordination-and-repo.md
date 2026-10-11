# Role 1: Coordination, repo and layout v2

| Owner | Hours | Test days | Works in |
|---|---|---|---|
| Kai (co-lead) | About 13: 6–7 for repo and coordination, 6–7 for the new layout; plus oversight (reviews, check-ins, helping anyone who's stuck) | Hosts the hardware, runs the checklist, tests the new layout on test day 2 | The whole repo, `Baseline-Protocol/Hardware/mea_device.py`, new `layouts.py`, `Project-Documentation/` |

**What this role is about:** two things.
1. **Coordination:** getting everyone started in a clean repo on Monday, getting the answers only the manufacturer and the hardware can give,
   running both test days, and turning test-day results into a clear fix list for each person. Kai is also the first person to message when
   anyone is stuck.
2. **Building the next encoding/decoding design (layout v2, below),** so round 2 can start with it. In it, stimulation goes in on the bottom
   row of electrodes and decisions are read from the top row, instead of both happening on the same half of the MEA.

| Due | What |
|---|---|
| Mon Oct 12 | Fixes 1 and 2; repo access; GitHub issues; shared-drive folder |
| Wed Oct 14 | Fix 3 |
| Fri Oct 16 | Layout v2, week-1 part: encoding, decoding, pulse scheduling, tests on the fake device; pull request open |
| Sat Oct 17 | Test-day checklist final |
| Mon Oct 19 | Test-day 1 results and fix lists |
| Fri Oct 23 | Layout v2, week-2 part: wired to the real stimulator setup, using the electrode map |
| Sun Oct 25 | Test day 2 (including a layout v2 run), then the "what's next" note |

---

## Fix 1: The repo is full of code that can't run (P23) · due Mon Oct 12 · about 1 h 15 min

**The bug.** A new member who follows the root README ends up in code that doesn't work:
- `Hardware-Pythonnet-Path/mea_integeration.py` imports `CMcsUsbBStimNet` and calls `CreateBStim`, `SetStimulationPattern` and
  `StartStimulation`. **None of these exist** in `McsUsbNet.dll` (checked against the DLL itself), so the file fails the moment it's
  imported, and `run_cartpole.py` there can't start.
- The root `spike.py` counts every *sample* above threshold instead of each spike. On pure noise it reports about 43 "spikes" per electrode
  per 50 ms.
- The root `square.py` treats the pole angle as degrees when CartPole gives radians, so its stimulation frequency barely moves (19.8–20.2 Hz
  instead of 10–30 Hz).
- The root README calls these folders the "full" version and sends new members to the Brian2 simulation first, which is out of scope.
- `McsUsbNet.dll` is committed twice (two identical 2 MB copies).

**Suggested solution.**
1. Create `archive/` and move `Hardware-Pythonnet-Path/`, the root `spike.py` and `square.py`, and `Brian2-Path/` into it, with a short
   `archive/README.md` listing the reasons above.
2. Decide with Ryan whether `Baseline-Protocol/Brian2/` stays (it's a teaching version); if it goes, update `Baseline-Protocol/README.md`.
3. Delete `Hardware-Pythonnet-Path/McsUsbNet.dll`; keep `Baseline-Protocol/Hardware/McsUsbNet.dll`.
4. Rewrite the root README: what the project is, "new members: read `Project-Documentation/README.md`", "active code:
   `Baseline-Protocol/Hardware/`".

**How to test it works.**
- `git grep -nE "(import|from) (spike|square|mea_integeration)([ ,]|$)" -- . ':!archive'` finds nothing, so no active code imports the
  archived files. (`spike_detection` is the new module and doesn't match.)
- `python Project-Documentation/Evidence/offline_checks.py` still runs.
- Ask someone who hasn't seen the repo to clone it and find the code they'd work on, using only the README.

---

## Fix 2: Three people would edit the same file at once · due Mon Oct 12 · about 1 h 15 min

**The bug.** Recording (role 3), stimulation (role 4) and spike detection (role 5) all live in one 227-line file,
`Baseline-Protocol/Hardware/mea_device.py`. With three people changing it in the same week, every merge would conflict.

**Suggested solution.** Split it into three files with **no behavior changes**:

| New file | Gets | Owner |
|---|---|---|
| `recording.py` | `_setup_recording`, `_on_data`, `read_spike_counts`, `SAMPLE_RATE`, `DATA_CHUNK_MS` | Role 3 |
| `stimulation.py` | `_setup_stimulation`, `stimulate_predictable`, `stimulate_unpredictable`, `_pulse_train`, `_send`, `HEADSTAGE`, stimulation constants | Role 4 |
| `spike_detection.py` | `count_spikes`, `SPIKE_THRESHOLD_SD`. **Must not import `clr`**, so it runs on any laptop. | Role 5 |

`mea_device.py` keeps the `MEADevice` class and its public methods, built from the two halves, so `run_hardware.py` doesn't change:
```python
# mea_device.py
from spike_detection import count_spikes, SPIKE_THRESHOLD_SD          # re-exported: old imports keep working
from recording import RecordingMixin, SAMPLE_RATE, DATA_CHUNK_MS
from stimulation import StimulationMixin, HEADSTAGE, STIM_AMPLITUDE_UV, PHASE_US, PULSES_PER_WINDOW

class MEADevice(RecordingMixin, StimulationMixin):
    def __init__(self): ...      # unchanged
    def connect(self): ...       # unchanged; calls self._setup_recording() and self._setup_stimulation()
    def close(self): ...         # unchanged (Ryan fixes it in role 2)
```

**How to test it works.**
- Save the output of `python Project-Documentation/Evidence/offline_checks.py` before the split and after it. The two must be identical
  (`diff before.txt after.txt` prints nothing). That script imports `mea_device.py` with stand-ins for the Windows-only parts, so it exercises
  the real code paths.
- `run_hardware.py` is unchanged.

---

## Fix 3: Questions only the manufacturer and the hardware can answer · due Wed Oct 14 · about 45 min

**The bug.** Four facts the code depends on aren't known yet:
1. **Which SCU input the headstage is in.** The signal collector unit (SCU) has inputs HS1–HS4, and the code's `HEADSTAGE` must be that number
   minus one. A wrong value sends stimulation to an empty input, with no error (P5).
2. **What the amplifier protection switch does.** The code turns it off; MCS's own example turns it on (P6).
3. **Which data stream carries the stimulator's timing signal** when the headstage is on HS3 or HS4 (P5).
4. **Whether we have the Test-60MEA test probe,** a dummy MEA that ships with the system. It decides how much test day can check.

**Suggested solution.**
- Look at the SCU, post the `HEADSTAGE` value in the team channel, and check the kit for the test probe.
- Email support@multichannelsystems.com:

> We control an MEA2100-Mini-System (headstage MEA2100-Mini-HS60 on SCU input HS_, IFB-C) from Python through McsUsbNet.dll. Three questions:
> (1) What does `CStg200xBasicNet.SetEnableAmplifierProtectionSwitch` do, and should it be on or off during voltage stimulation with
> blanking enabled? (2) With the headstage on SCU input HS3 or HS4, which data stream carries the stimulator sideband, given that
> `DigitalDatastreamEnableEnumNet` only offers Hs1/Hs2 sideband flags? (3) For recording with the Mini, is
> `ChannelBlock.SetSelectedChannels(...)` the recommended setup call?

**How to test it works.** `HEADSTAGE` is in Ryan's settings file before test day; the test-probe answer is posted; MCS's answers are written
into the settings table in `System-Overview.md`. If MCS hasn't answered by Oct 21, send a reminder.

---

## Feature: Layout v2, separate input and output electrodes · week 1 due Fri Oct 16, week 2 due Fri Oct 23 · about 6–7 h

**The problem it solves (P19).** Today the same half of the MEA both *receives* the stimulation and *votes* on the action. The side the pole
leans toward gets stimulated, and spikes on that side push the cart toward the lean, which is the correct move. So anything that makes the
stimulated electrodes look active wins the game without any learning:
- the neurons right under the electrodes simply responding,
- stimulation artifacts.

That reflex alone scores about 30–43 steps against about 22 for coin flips. Both published studies we build on kept input and output
electrodes separate for exactly this reason. DishBrain said its separate layout "precludes a direct relationship between input stimulation and
output activity", and the UCSC organoid study chose distinct input, output and training units.

**The design** (Kai's sketch, standard 8 × 8 MEA layout with 60 electrodes and one reference electrode):

```
        L   L   L   R   R   R          top row: DECODE (output)
    o   o   o   o   o   o   o   o         left 3 more active  → push left (0)
    o   o   o   o   o   o   o   o         right 3 more active → push right (1)
    o   o   o   o   o   o   o   o
 ref    o   o   o   o   o   o   o      (reference electrode: never stimulated, never counted)
    o   o   o   o   o   o   o   o
    o   o   o   o   o   o   o   o
        L   L   L   R   R   R          bottom row: ENCODE (input)
                                          pole leans left  → pulses on the left 3
                                          pole leans right → pulses on the right 3
                                          pulse rate (Hz) ← angular velocity
```

**Why this can be built now:** none of it needs cells or a new experiment. It's an alternative to the baseline's `feedback.py` rules, selected
in Ryan's settings file (`layout = "baseline"` or `"rows"`). **The baseline stays the default for every round-1 test.** Layout v2 just has to
be built, tested on the fake device, and checked once on the hardware on test day 2, so round 2 can start with it.

### Decisions to make first (write them at the top of `layouts.py`)
1. **What the pulse rate encodes.** Rate can't carry a sign, so encoding the plain speed |θ̇| loses whether the pole is *falling further*
   or *recovering*. Suggested: rate follows the **falling speed**, `θ̇ × sign(θ)`. That's positive when the pole moves away from vertical
   (higher rate) and negative when it's recovering (floor rate).
2. **Rate range and cap.** Suggested 4–40 Hz (DishBrain's range), capped at 40 Hz. A falling pole getting more pulses means worse play gets
   a bigger stimulation "dose", which is one of the effects Feldman warned can masquerade as learning. Capping the rate keeps that bounded,
   and every pulse is logged (role 7) so the dose can be checked.
3. **How many decoding electrodes.** With 3 electrodes per side and 100 ms windows, the left and right counts are *equal* (a coin flip)
   **42–60% of the time** at typical resting rates of 1–2 Hz per electrode. That drops to 22–33% with 300 ms of data, and 12–17% with 30
   electrodes per side. Suggested:
   - smooth each side's count across steps with a moving average, `r = α·r_prev + (1−α)·count` with α = 0.2 (what the UCSC study used);
   - make the decode group a setting (top row, or top two rows), so it can be widened if ties dominate.
4. **What a tie does.** Suggested: repeat the previous action, rather than a coin flip, once smoothing is in. Either way, log it.

### Suggested implementation

**Week 1 (on your laptop, about 5 h)**
1. `layouts.py` with two classes sharing one interface (2 h):
```python
class Layout:
    def encode(self, observation, now_us) -> StimPlan: ...       # which electrodes go on each generator, pulse onsets this window
    def decode(self, counts_per_electrode) -> int: ...          # 0 = push left, 1 = push right

class BaselineLayout(Layout): ...   # today's rules from feedback.py, unchanged
class RowsLayout(Layout):           # layout v2
    def __init__(self, cfg, electrode_map): ...                 # encode/decode groups by electrode NAME, looked up via channel_map.py
```
   Refer to electrodes by their **names on the MEA layout**, not raw indices. Role 4's `channel_map.py` turns names into stimulator and
   recording indices; until it's verified in week 2, use MCS's standard layout table. Mind the MEA's orientation: the manual (p. 13) warns an
   MEA put in the wrong way round scrambles the layout, so "top row" only means top if the MEA sits the right way.
2. **A pulse scheduler that runs continuously across steps** (1.5 h). At 4 Hz there's one pulse every 250 ms, longer than a 100 ms game step,
   so "N pulses per window" doesn't work. Keep `next_pulse_us` from one step to the next. Each step, place pulses at `1 / rate` spacing up
   to the end of the window, rounded to the stimulator's 20 µs grid, and carry the leftover time forward. Feed the result into role 4's
   `validate_train` and their pulse-schedule logging.
3. **Tests, plus a fake-device option** (1.5 h). Agree with role 6 to add `propagation=p` to the fake device: stimulating the bottom-left group
   raises firing on the top-left group with probability `p` (same on the right). That stands in for a network that carries the signal.

**Week 2 (with the electrode map, about 2 h)**
4. With role 4: the stimulator setup enables only the layout's 6 input electrodes (3 per generator) and grounds the rest; the baseline keeps
   all 60. Use the real names-to-indices map from their electrode sweep, if we had the test probe. (1 h)
5. Run it on test day 2; it's already in the checklist as part of check 6. (1 h, including the run)

### How to test it works

**Laptop (unit tests):**
- `encode`:
  - a negative angle puts pulses only on the left 3, a positive angle only on the right 3;
  - the rate rises with falling speed and never exceeds 40 Hz;
  - across 100 consecutive steps at a constant rate, the gap between every pair of pulses is the same (±20 µs), including across step
    boundaries;
  - every pulse time is on the 20 µs grid.
- `decode`:
  - changing the counts on any electrode *outside* the top row never changes the action;
  - the reference electrode is never used;
  - `decoder_mapping = "swapped"` flips the action.

**Laptop (fake device):**

| Fake culture | Expected average game length | What it shows |
|---|---|---|
| No propagation | ≈ 22 steps (coin flip) | v2 doesn't invent a signal |
| Artifacts on the stimulated (bottom-row) electrodes only | ≈ 22 steps | **The key difference from the baseline,** where artifacts alone give 30+ |
| Propagation `p` = 0.5 | Clearly above 22 | v2 can carry a real signal when the network carries it |

**Test day 2 (hardware, no cells):**
- A short layout v2 session runs without errors.
- The timing stream shows pulses at the intended rate.
- With the test probe, the stimulation shows up most strongly on the bottom-row channels.
- The closed loop averages about 22 steps.

---

## Coordination work

| When | What | About |
|---|---|---|
| Mon Oct 12 | Everyone can push branches; `main` requires a pull request and one review; one GitHub issue per role, linking its doc; shared-drive folder for recordings | 30 min |
| Wed Oct 14, Wed Oct 21 | 15-minute check-ins | oversight |
| Ongoing | Review pull requests; help anyone who's stuck | oversight |
| Sat Oct 17 | Finalize `Test-Day-Run-Sheet.md` with the exact script names from the merged code; confirm everything is merged | 30 min |
| Sun Oct 18 | Bring and connect the hardware; run the checklist with Ryan; package the data on the shared drive with a README saying what each file is | 30 min plus hosting |
| Mon Oct 19 | Post the results table, the settings found, and a **fix list per person** (what failed, the error, which file) | 1 h |
| Sun Oct 25 | Host test day 2; write a short "what's next" note: what passed, what's open, and round-2 starting points (second MEA, artifacts on real electrodes, first cell sessions, controls) | 45 min plus hosting |

## Done when
- The repo is cleaned up and split by Monday.
- Both test days ran, with results and data posted.
- Everyone got a fix list after test day 1.
- The "what's next" note is written.
- Layout v2 passes its unit and fake-device tests, and one v2 session runs on the hardware on test day 2.
