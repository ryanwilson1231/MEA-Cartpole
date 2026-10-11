# Role 4: Stimulation

| Owner | Hours | Test days | Works in |
|---|---|---|---|
| Open (most comfortable debugging hardware code) | 9 | Present at both (runs checks 2, 3 and 4) | `Baseline-Protocol/Hardware/stimulation.py` (after Kai's Monday split), new `channel_map.py` |

**What this role is about:** sending pulses *into* the culture exactly as intended. The stimulator must connect reliably, both stimulus
generators must deliver identical pulses, nothing unsafe can be sent, and every pulse must be written down.

**Background:** the headstage has two stimulus generators. The code wires electrodes 0–29 ("left") to generator 1 and 30–59 ("right") to
generator 2. Each game step it sends two 75 mV pulses (200 µs positive, then 200 µs negative) to the side the pole leans toward.

**Before writing any call into the MCS library,** look up its real signature in `Project-Documentation/Evidence/McsUsbNet-API-reference.md`.
For laptop testing, `Evidence/offline_checks.py` shows how to stand in for the Windows-only modules.

| Due | What |
|---|---|
| Fri Oct 16 | Fixes 1–6, fix 7 part 1, both check scripts; pull request open |
| Sun Oct 18 | Test day 1: checks 2, 3 (with role 3) and 4 |
| Fri Oct 23 | Fix 7 part 2, fix 8, your test-day fix list |
| Sun Oct 25 | Test day 2 |

---

## Fix 1: The stimulator connection is never checked (P2) · due Fri Oct 16 · about 15 min

**The bug.**
```python
status = self.dacq.Connect(entry)          # recording side: checked
if status != 0:
    raise RuntimeError(...)
self.stg = CStg200xDownloadNet()
self.stg.Connect(entry)                    # stimulator: return value ignored
```
`Connect` returns a status code (0 = success). If the stimulator fails to connect, recording still works and the game still runs, but there's
no stimulation at all. Results look like coin flips, so nothing seems broken.

**Suggested solution.**
```python
status = self.stg.Connect(entry)
if status != 0:
    raise RuntimeError(f"Could not connect to the stimulator (status {status})")
```
If it fails on test day, try `self.stg.Connect(entry, 1)` (with a lock mask, as MCS's example does); the DLL has both versions.

**How to test it works.**
- **Laptop:** a stand-in whose `Connect` returns 1 makes `connect()` raise.
- **Test day (check 2):** the script prints status 0.

---

## Fix 2: Only one generator is put in voltage mode (P4) · due Fri Oct 16 · about 15 min

**The bug.**
```python
self.stg.SetVoltageMode(0)
```
The DLL has two versions: `SetVoltageMode()` sets every channel, and `SetVoltageMode(uint channel)` sets one. Passing `0` picks the
one-channel version, for channel 0 only. Pulses go to stimulator channel `2 * HEADSTAGE + 0` (left) and `2 * HEADSTAGE + 1` (right). So with
`HEADSTAGE = 0`, the right generator is never set to voltage mode, and with any other `HEADSTAGE`, neither is. The generators also support
current mode (manual: ±1 mA or ±10 V). If one is in current mode, the same number (75,000) means a current instead of a voltage, the two
sides get physically different stimulation, and every left-vs-right decision is biased.

**Suggested solution.** `self.stg.SetVoltageMode()` with no argument.

**How to test it works.**
- **Laptop:** a stand-in asserts `SetVoltageMode` was called with no arguments.
- **Test day (check 2):** no errors. With the test probe, fix 8 compares left and right pulses in the recordings: they must match.

---

## Fix 3: The amplifier protection switch is turned off (P6) · due Fri Oct 16 · about 15 min

**The bug.**
```python
self.stg.SetEnableAmplifierProtectionSwitch(HEADSTAGE, electrode, False)
```
The manual doesn't describe this switch, and MCS's own example sets it to `True`. Going by its name, it protects the recording amplifiers
during stimulation. Turning it off with no reason given could mean bigger artifacts or saturated amplifiers.

**Suggested solution.** Set it to `True`, with a comment that we're matching MCS's example until MCS answers (Kai is asking them). If MCS
says otherwise, change it and update the comment.

**How to test it works.**
- **Laptop:** a stand-in asserts `True` for all 60 electrodes.
- **Test day:** no errors. If MCS answers, the decision goes into `System-Overview.md`.

---

## Fix 4: `HEADSTAGE` is hard-coded (P5) · due Fri Oct 16 · about 15 min

**The bug.** `HEADSTAGE = 0` assumes the headstage is plugged into SCU input HS1. It's the number of the SCU input minus one (the library
calls this parameter `Scu_HS`). MCS's example uses 3 (HS4). A wrong value sends every pulse to an empty input, **with no error**.

**Suggested solution.** Read it from Ryan's settings file (`config.headstage`). Kai posts the real value by Wednesday.

**How to test it works.** On test day, check 3 sees the timing stream change at every pulse train, so the stimulator is driving the
headstage we're recording from. With the test probe, check 4 sees pulses on the recording channels.

---

## Fix 5: Nothing stops an unsafe pulse from being sent · due Fri Oct 16 · about 1 h

**The bug.** `_pulse_train` and `_send` upload whatever the constants say. A typo such as `STIM_AMPLITUDE_UV = 750_000` (750 mV instead of 75)
or `PHASE_US = 2000` would go straight to the stimulator. Separately, the stimulator works in 20 µs steps (manual), so any duration that
isn't a multiple of 20 µs can't be played as written.

**Suggested solution.** Check every pulse train just before it's uploaded:
```python
MAX_AMPLITUDE_UV = 150_000      # 150 mV: the highest DishBrain used; raise only after review
MAX_PHASE_US = 500

def validate_train(amplitudes, durations):
    if any(abs(a) > MAX_AMPLITUDE_UV for a in amplitudes):
        raise ValueError("amplitude above limit")
    if any(d % 20 for d in durations):
        raise ValueError("duration not a multiple of 20 us")
    # every pulse: +A for PHASE_US, then -A for PHASE_US (charge balanced), each phase <= MAX_PHASE_US
    ...
```

**How to test it works.** Unit tests:
- The current settings pass, for predictable, unpredictable, and 2,000 random unpredictable trains.
- Each of these is rejected: 750 mV; a 210 µs phase; a positive phase with no matching negative; a 600 µs phase.

---

## Fix 6: Delivered pulses aren't recorded · due Fri Oct 16 · about 1 h

**The bug.** `stimulate_predictable` and `stimulate_unpredictable` return nothing, and the run saves only episode lengths. So there's no record
of which pulses went where, or when. Later experiments need exactly that: the stimulation "dose" each electrode received, and replaying a
session's exact stimulation to another culture as a control.

**Suggested solution.** Return a schedule from both functions, e.g. a list of `(onset_us, generator, kind)` for every pulse
(`kind` = `"predictable"` or `"unpredictable"`). Role 7's logger saves it every step.

**How to test it works.** Unit tests:
- `stimulate_predictable("left")` returns 2 pulses on generator 1 at 0 and 50,000 µs, and nothing on generator 2.
- `stimulate_unpredictable()` returns 2 pulses on each generator, inside the 100 ms window, not overlapping.
- Test day 1 data (week 2): the number of logged pulses matches the number seen in the timing stream.

---

## Fix 7: "Left" and "right" electrodes haven't been checked (P15) · part 1 due Fri Oct 16, part 2 due Fri Oct 23 · about 1 h 30 min

**The bug.** In `feedback.py`:
```python
LEFT_CHANNELS = list(range(0, 30))
RIGHT_CHANNELS = list(range(30, 60))
```
These are the first and last 30 *data channels* in amplifier order. Nobody has checked that they're the physical left and right halves of
the MEA. The stimulator's electrode numbers may not follow the recording's channel numbers either. The manual also warns that an MEA put in
the wrong way round scrambles the layout, and some MEAs use one position for a reference electrode that records nothing.

**Suggested solution.**
- **Part 1 (week 1):** create `channel_map.py` holding the left and right lists for both numberings (stimulator and recording), defaulting to
  today's 0–29 / 30–59, and make `feedback.py` and the stimulation setup import from it. Also store each electrode's **name** on the MEA
  layout, with a lookup from name to stimulator index and recording index. Kai's layout v2 picks its top and bottom rows by name.
  Make `_setup_stimulation` accept which electrodes go on each generator: the baseline uses all 60, layout v2 only 6. Write
  `electrode_sweep.py`: put one electrode at a time on generator 1, send 10 pulses, and save the recording for each electrode.
- **Part 2 (week 2, only if we had the test probe):** from the sweep data, find which recording channel shows each stimulated electrode's
  pulse, and fill in `channel_map.py`. The physical left/right split needs the MEA's layout, from MCS's datasheet for our MEA type.

**How to test it works.**
- **Laptop:** `feedback.py` behaves the same with the default map (role 6's tests).
- **Test day (check 4, test probe only):** every stimulated electrode lights up exactly one recording channel, and the table has 60 rows with
  no duplicates.

---

## Fix 8: Did the stimulator play what we sent? · due Fri Oct 23 (week 2, using the recordings) · about 2 h

**The bug.** We upload pulse trains but have never checked what actually came out of the stimulator.

**Suggested solution.** Using the test-day recordings and the timing stream (role 3):
1. **Always:** count the pulses per train, measure their spacing, and check each lasts 400 µs (2 × 200 µs). They should match fix 6's
   schedule.
2. **Test probe only:** average the recorded signal around left pulses and around right pulses. The two should match in size and shape
   (proves fix 2 worked). Then measure how long after a pulse the signal takes to settle back to normal noise. That number becomes role 5's
   **artifact window**.

**How to test it works.** Pulse count, spacing and width match the schedule for every train in the recording. With the probe, left and right
average artifacts are within a few percent of each other, and the artifact window is sent to role 5.

---

## Test-day check scripts · due Fri Oct 16 · about 2 h (includes `electrode_sweep.py` from fix 7)

| Script | Does | Passes when |
|---|---|---|
| `hw_check_stimulation.py` (check 2) | Connects (prints the status); sets voltage mode; plays 20 pulse trains left-only, 20 right-only and 20 on both sides, while role 3's recorder saves every stream; logs every pulse's time | Status 0, no errors, recording saved, pulse log saved |
| `electrode_sweep.py` (check 4, test probe only) | One electrode at a time on generator 1, 10 pulses each, saving each electrode's recording | 60 recordings saved |

## Done when
- Check 2 passes on test day 2.
- The safety limits and schedule are tested.
- The stimulator is confirmed to play exactly what we send.
- With the test probe: the channel map and artifact window are delivered.
