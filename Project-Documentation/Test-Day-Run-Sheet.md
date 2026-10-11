# Test Day Run Sheet

For **test day 1 (Sun Oct 18)** and **test day 2 (Sun Oct 25)**. Run the steps in order: each one depends on the one before.
Kai finalizes this sheet each Saturday with the exact script names from the merged code.

## The day before (Saturday)

- [ ] All pull requests for the week merged into `main`.
- [ ] Ryan pulls `main` and runs the full loop on the fake device without errors.
- [ ] Ryan's computer passes the DLL smoke test (`SETUP-WINDOWS.md`).
- [ ] At least 20 GB free on Ryan's computer.
- [ ] Shared-drive folder created for the day's data.
- [ ] Hardware packed:
  - headstage, signal collector unit (SCU), interface board
  - the interface board's power supply
  - headstage cable (to the SCU), iX cable (SCU to interface board), USB-C cable
  - the Test-60MEA test probe, if it's in the kit

## Setup (about 30 min)

1. Connect everything **with the interface board switched off**. The headstage cable plugs into the SCU with its red dot facing up; note
   which SCU input it's in (HS1–HS4). That number minus one is `HEADSTAGE`. Plug the USB-C cable **directly into the laptop**, with no
   hub or dock. Then switch on (manual p. 12).
2. Put the test probe in the headstage if we have it. Otherwise leave it empty.
3. Open Multi Channel Experimenter and check it sees the device.
   - With the test probe: click "Start DAQ" and check for about **20 µV peak-to-peak noise** on every channel (manual p. 11).
   - Without it: the signals won't mean anything (the inputs are open). Just check that data appears.
4. Open MCS Filter Configuration (a separate small program from MCS; see `SETUP-WINDOWS.md`) and write down the headstage's high-pass
   and low-pass filter settings. Don't change them.
5. **Close both MCS programs.** Only one program can control the device at a time.

## Checks

| # | Check | Owner | Passes when |
|---|---|---|---|
| 1 | Recording check script | Role 3 | Connects; prints the number of data streams; about 50 data callbacks per second; no short reads over 5 min; samples received = 50,000 × seconds; prints µV per count. Saves **3 min of raw data**. |
| 2 | Stimulation check script | Role 4 | Stimulator connects (status 0); both generators set to voltage mode; left-only, right-only and both-sides pulse trains upload and play with no errors; recording runs at the same time and is saved. |
| 3 | Find the timing stream | Roles 3 and 4 | Identifies which data stream changes at each pulse. Write its index in `System-Overview.md`. |
| 4 | Electrode sweep (**test probe only**) | Role 4 | One electrode stimulated at a time; table of stimulator electrode → recording channel saved. |
| 5 | Startup and shutdown | Ryan | A deliberately broken setup run twice in a row: the second run gets as far as the first, without power-cycling. |
| 6 | Full session | Ryan, role 7 | `spontaneous` 2 min, then `closed_loop` 5 min: runs to the end, the session folder is complete, and the report notebook runs on it. *(Test day 2: spontaneous → stimulation check → closed loop 10 min → spontaneous, then a 5-minute closed loop with `layout = "rows"`, layout v2, run by Kai.)* |
| 7 | Package the data | Kai | Everything copied to the shared drive, with a short README saying what each file is and which check produced it. |

**What results to expect without cells:** there are no neurons, so any "spikes" are noise or artifacts. In the closed loop, a working
pipeline should average roughly **22 steps per episode** (coin-flip level) with left and right actions about 50/50. Clearly more than
that, or actions that follow the stimulated side, means stimulation artifacts are getting into the decisions. Write it down; that's
useful data, not a failure of the day.

**Data size:** raw recording is about 12 MB per second, so 3 minutes is about 2.2 GB. Keep raw recordings short.

## Results (fill in on the day)

| # | Check | Pass / fail | Notes (errors, numbers, files saved) |
|---|---|---|---|
| 1 | Recording | | |
| 2 | Stimulation | | |
| 3 | Timing stream | | |
| 4 | Electrode sweep | | |
| 5 | Startup / shutdown | | |
| 6 | Full session | | |
| 7 | Data packaged | | |

Settings found: SCU port / `HEADSTAGE` = ___ · hardware filter = ___ · µV per count = ___ · number of data streams = ___ ·
timing stream index = ___ · test probe available: yes / no
