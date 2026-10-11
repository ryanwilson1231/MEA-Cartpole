# Role 7: Logging and analysis

| Owner | Hours | Test days | Works in |
|---|---|---|---|
| Open | 8 | On call; runs the report on the day's session if possible | New `Baseline-Protocol/Hardware/session_logger.py`, new `analysis/session_report.ipynb` |

**What this role is about:** making every run leave a complete record, and turning that record into a report that shows at a glance whether
the system behaved. Everything runs on a laptop, using the fake device (role 6) in week 1 and real test-day data in week 2.

| Due | What |
|---|---|
| Tue Oct 13 | Log format agreed with Ryan |
| Fri Oct 16 | Fixes 1 and 2; pull request open |
| Fri Oct 23 | Fix 3, your test-day fix list |

---

## Fix 1: Almost nothing is saved (P17) · due Fri Oct 16 · about 3 h 30 min

**The bug.** At the end of a run, `run_hardware.py` saves one file:
```python
np.savetxt("episode_lengths.csv", episode_lengths, fmt="%d", header="steps", comments="")
```
Nothing records the pole angles, the actions, the spike counts, the stimulation, or the settings used. If a run looks wrong, there's no way
to tell whether the decoder was stuck, artifacts were driving the game, or nothing was firing. And if the program crashes, even the episode
lengths are lost: the file is only written at the very end. Later experiments (stimulation dose per electrode, replaying a session's
stimulation as a control) need all of this recorded.

**Suggested solution.** Agree the format with Ryan by Tuesday, then write `session_logger.py` with `start_session(metadata)`,
`log_step(...)`, `log_pulses(...)` and `close()`. Each session gets its own folder, `sessions/YYYY-MM-DD_HHMM_<label>/` (add `sessions/` to
`.gitignore`):

| File | Contents |
|---|---|
| `session.json` | Date and time, operator, mode, what was in the headstage (test probe / empty / MEA ID), `HEADSTAGE`, µV per count, **the full settings file**, git commit hash, notes |
| `steps.csv` | One row per game step: episode, step, time, first sample of the listening window, cart position and velocity, pole angle and angular velocity, feedback type, stimulated side, left count, right count, tie (yes/no), action |
| `counts.npz` | The 60 per-electrode spike counts for every step |
| `stim_schedule.csv` | Every pulse: time (or sample number), generator or side, type (from role 4's fix 6) |
| `spontaneous_*.npz`, `stim_check.npz` | Outputs of Ryan's other modes |

Write rows as they happen (append and flush), not at the end.

**How to test it works.**
- **Laptop:** a 5-minute fake-device session produces every file; `steps.csv` has one row per step; `session.json` contains every config
  field.
- **Laptop:** kill the program halfway through. Everything up to that moment is still on disk and readable.
- **Test day (check 6):** the real session leaves a complete folder.

---

## Fix 2: There's no quick way to judge a run · due Fri Oct 16 · about 2 h 30 min

**The bug.** The only output is a plot of game lengths. Nothing compares a run against what different failure modes look like, and nothing
warns when something is off. You'd have to dig through raw files to notice that the cart was pushed the same way every step.

**Suggested solution.** `analysis/session_report.ipynb`: point it at a session folder and it shows:
- game lengths against the reference levels from `System-Overview.md`:

  | Average game length | Means |
  |---|---|
  | ≈ 9 steps | stuck |
  | ≈ 22 steps | coin flip, no usable signal |
  | 30–43 steps | "reflex": the stimulated side responds |

- the left/right action split and how often windows tied;
- **policy quality:** the share of steps where the action pushed toward the side the pole leaned (1.0 = perfect reflex, 0.5 = coin flip);
- left and right spike counts over time, and their ratio;
- each electrode's spike rate over the session;
- stimulation dose per electrode, by type.

It also prints **warnings** automatically:
- **Stuck:** one action on more than 80% of steps.
- **Possible artifacts:** a session with no neurons averaging 30+ steps, or actions matching the stimulated side on more than 60% of
  steps.
- **Incomplete log:** missing files or rows.

**How to test it works.** Use role 6's fake-device options to make three runs:
- a normal one: no warnings;
- one with `imbalance` (stuck): the "stuck" warning fires;
- one with `artifacts=True`: the "possible artifacts" warning fires.

---

## Fix 3: The report has only seen fake data · due Fri Oct 23 (week 2) · about 2 h

**The bug.** Until test day, the logger and report have only ever seen fake-device sessions.

**Suggested solution.**
- Run the report on test day 1's real session folder and fix whatever is missing or wrong (real data has gaps and quirks fake data doesn't).
- Add sections for Ryan's `spontaneous` and `stim_check` outputs:
  - per-electrode resting rates;
  - responses after left pulses vs right pulses.

**How to test it works.** On test day 2, the full `session` run produces a complete folder, and the report runs on it start to finish
without anyone editing it by hand.

## Done when
- Test day 2's session produces a complete folder and a full report with no manual fixes.
- The warnings fire correctly on the deliberately bad fake runs.
