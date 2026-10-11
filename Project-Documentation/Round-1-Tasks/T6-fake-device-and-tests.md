# Role 6: Fake device and tests

| Owner | Hours | Test days | Works in |
|---|---|---|---|
| Open | 7 | Not needed (on call) | New `Baseline-Protocol/Hardware/fake_mea_device.py`, new `Baseline-Protocol/Hardware/tests/`, `requirements.txt` |

**What this role is about:** making it possible for everyone to build and check their code without the hardware. Your fake device is what
the rest of the team tests on in week 1, so **it's due Wednesday**.

| Due | What |
|---|---|
| **Wed Oct 14** | Fix 1 (fake device) |
| Fri Oct 16 | Fixes 2 and 3; pull request open |
| Fri Oct 23 | Fix 4 (replay mode), your test-day fix list |

---

## Fix 1: The hardware code can't run on a laptop (P21) · due Wed Oct 14 · about 2 h 30 min

**The bug.** `mea_device.py` loads the MCS library the moment it's imported:
```python
import clr
clr.AddReference(str(Path(__file__).parent / "McsUsbNet.dll"))
from Mcs.Usb import (...)
```
The library contains native Windows code, so on a Mac this fails immediately. Without a stand-in, nobody can run `run_hardware.py` except on
Ryan's computer with the hardware plugged in. That means five people waiting for one laptop, and every bug found only on test day.

**Suggested solution.** `fake_mea_device.py` with a `FakeMEADevice` class that has **the same public methods** as `MEADevice`:
`connect()`, `stimulate_predictable(side, window_ms)`, `stimulate_unpredictable(window_ms)`, `read_spike_counts(window_ms)` (returns 60
counts) and `close()`. It must not import `clr`. Spikes are random (Poisson) at a rate you set per electrode. Add options that reproduce the
outcomes we worry about:

| Option | Simulates | Expected average game length |
|---|---|---|
| `imbalance=2.0` | One half fires twice as much (decoder stuck) | ≈ 9 steps |
| (none) | No usable signal | ≈ 22 steps (coin flip) |
| `evoked_spikes=N` | Extra spikes on the stimulated side (a "reflex") | 30–43 steps, depending on N |
| `artifacts=True` | Fake stimulation artifacts on the stimulated side | 30+ steps (what artifacts leaking would look like) |
| `propagation=p` (for Kai's layout v2) | Stimulating one group of electrodes raises firing on a different group with probability `p` | Agree the details with Kai; see layout v2 in role 1's doc |

With Ryan, add `use_fake_device` to the settings file so `run_hardware.py` picks the fake or the real device.

**How to test it works.**
- `run_hardware.py` with the fake device runs 20 games on a Mac.
- Each option's average game length lands in the expected range above (over 100+ games). That also proves the reference table in
  `System-Overview.md`.

---

## Fix 2: There are no automatic tests · due Fri Oct 16 · about 2 h

**The bug.** Nothing checks the code automatically, so a broken change is only discovered on test day, on the hardware, in front of everyone.

**Suggested solution.** A `pytest` suite in `Baseline-Protocol/Hardware/tests/`:

| Test file | Checks |
|---|---|
| `test_feedback.py` | Balance limit (0.15 rad), lean side (negative angle = left), decoding (more left = 0, more right = 1, ties random but always 0 or 1) |
| `test_pulse_trains.py` | Every train is exactly 100 ms; every duration is a multiple of 20 µs; every pulse is +A then −A (balanced). Reuse `Project-Documentation/Evidence/offline_checks.py` section 2. |
| `test_safety.py` | Role 4's safety limits reject bad trains |
| `test_spike_detection.py` | Role 5's detector tests |
| `test_fake_loop.py` | One full game on the fake device, start to finish |

Use the stand-in trick from `offline_checks.py` to import the hardware modules without the DLL.

**How to test it works.**
- `pytest` passes from the repo root.
- Break something on purpose (set `PHASE_US = 210`) and a test fails; undo it.

---

## Fix 3: Package versions aren't pinned (P22) · due Fri Oct 16 · about 30 min

**The bug.** `requirements.txt` lists package names with no versions:
```
numpy
scipy
matplotlib
gymnasium
brian2      # Brian2 version only
pythonnet   # Hardware version only (Windows)
```
Laptops and Ryan's computer can end up with different versions. `pythonnet` 2 and 3 in particular handle function arguments differently, and
our code is written for 3.

**Suggested solution.** Pin exact versions (`numpy==…`) that work on both Ryan's computer (he sends his versions Wednesday) and a Mac. Mark
`pythonnet` as Windows-only (`pythonnet==3.x.x; sys_platform == "win32"`), and move `brian2` to a separate optional file if the Brian2 folder
stays.

**How to test it works.** In a fresh virtual environment on a Mac, `pip install -r requirements.txt` succeeds and `pytest` passes. Ryan
installs the same file on his computer without errors.

---

## Fix 4: Test-day recordings can't be used without the hardware · due Fri Oct 23 (week 2) · about 1 h 30 min

**The bug.** After test day 1 we'll have real recordings, but the code can only get data from the live hardware, so roles 3, 5 and 2 can't
test against real data on their laptops.

**Suggested solution.** A **replay** option on the fake device. Load a test-day raw recording (`.npy` from role 3) and serve it window by
window through the same code path the real device uses, including role 5's detector and role 3's pulse positions if the timing stream was
recorded. Commit a small slice (a few MB) as a test fixture; the full recordings stay on the shared drive.

**How to test it works.**
- Replaying a recording gives the same spike counts as running role 5's detector directly on the same samples.
- Ryan's Saturday Oct 24 dry run uses replay mode end to end.

## Done when
- Everyone used the fake device in week 1.
- `pytest` passes.
- Replay mode works on test day 1's data.
