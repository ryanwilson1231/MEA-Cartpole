# Role 5: Spike detection

| Owner | Hours | Test days | Works in |
|---|---|---|---|
| Open | 8 | Not needed (on call) | `Baseline-Protocol/Hardware/spike_detection.py` (after Kai's Monday split). No hardware, no Windows. |

**What this role is about:** turning raw voltages into spike counts, which decide every move in the game. The goal is a detector that reports
real spikes and almost nothing else. All of this runs on a Mac with numpy and scipy.

**Start here:** run `python Project-Documentation/Evidence/offline_checks.py`. Section 1 reproduces fix 1's bug.

**How the current detector works** (`count_spikes`): for each 100 ms window,
1. filter to 300–3000 Hz (where spikes live);
2. estimate each electrode's noise level as `median(|signal|) / 0.6745`;
3. count every time the signal dips below −5 × noise.

That's a standard method. The bugs are in how it's applied.

| Due | What |
|---|---|
| Fri Oct 16 | Fixes 1–5 with tests; pull request open |
| Fri Oct 23 | Fix 6 (real data), your test-day fix list |

---

## Fix 1: The detector invents spikes at the edges of every window (P13) · due Fri Oct 16 · about 1 h 30 min

**The bug.**
```python
filtered = sosfiltfilt(sos, voltages, axis=1)     # each 100 ms window filtered on its own
```
A filter needs a few milliseconds to "settle" when it starts, and `sosfiltfilt` starts fresh at both ends of every short window. The
settling swings cross the threshold. On **pure noise with no spikes at all**, the current detector reports:

| | |
|---|---|
| False spikes per electrode per 100 ms window | 0.15, about 1.5 fake spikes per second per electrode |
| Share of them within 2 ms of a window edge | 100% |
| What it should be at −5 × noise | about 0.0014 |

A real culture at rest fires about 1–5 times per second per electrode, so the fake rate is as big as the real signal. It hits both halves
equally, so it doesn't push decisions to one side, but it buries the real differences.

**Suggested solution (tested).** Filter a slightly longer window, then count only the middle. Take the 100 ms you want plus 10 ms on each side
(role 3's `get_window` can hand you that), run the same filter over all 120 ms, throw away the 10 ms margins, and count only in the middle
100 ms. The settling swings land in the margins.
```python
def count_spikes(window_uv, fs, noise_sd, pulse_samples=(), mask_ms=3.0, margin_ms=10.0, threshold_sd=5.0, refractory_ms=1.0):
    margin = int(fs * margin_ms / 1000)
    filtered = sosfiltfilt(SOS, window_uv, axis=1)[:, margin:-margin]   # drop the margins after filtering
    ...
```
Tested on pure noise: false spikes drop from **0.144 to 0.0004 per electrode per window**.

**How to test it works.** Unit test: 50 windows of pure noise (60 electrodes, with margins) give **≤ 0.01** false spikes per electrode per window.

---

## Fix 2: One spike can be counted twice · due Fri Oct 16 · about 30 min

**The bug.**
```python
new_crossings = below[:, 1:] & ~below[:, :-1]
return new_crossings.sum(axis=1)
```
Every time the signal re-enters the "below threshold" zone counts as a new spike. A spike whose trough wiggles across the threshold gets counted
twice within a fraction of a millisecond. In the offline check, 133 planted spikes came out as 138.

**Suggested solution.** A refractory period: on each electrode, ignore any crossing within 1 ms of the previous counted one. A real neuron
can't fire twice that fast.

**How to test it works.** Unit test with planted spikes (`offline_checks.py` section 1b shows how): **≥ 95% found and ≤ 5% extra.** With
fixes 1 and 2 together, a trial found 150 of 150 planted spikes, with every electrode exact.

---

## Fix 3: The threshold moves with the activity · due Fri Oct 16 · about 30 min

**The bug.**
```python
noise = np.median(np.abs(filtered), axis=1) / 0.6745     # re-estimated in every 100 ms window
```
The noise level is re-measured from the same 100 ms you're counting in. A burst of real activity raises its own threshold and hides
itself, and a very quiet window lowers the threshold and lets noise through.

**Suggested solution.**
- `calibrate_noise(recording_uv, fs)`: estimate each electrode's noise once per session, from the spontaneous recording at the start
  (role 2's `spontaneous` mode), and store it.
- `count_spikes` takes `noise_sd` as an input instead of computing it. Fall back to the per-window estimate only if no calibration exists.

**How to test it works.** Unit test: calibrate on noise, then count a window with lots of planted spikes. The threshold used equals the
calibrated one (not raised by the spikes), and ≥ 95% of the spikes are found.

---

## Fix 4: Stimulation artifacts get counted as spikes (P14) · due Fri Oct 16 · about 1 h

**The bug.** The detector has no idea when stimulation pulses happen. Each pulse leaves an electrical artifact on the stimulated electrodes,
and the hardware's blanking only hides it during the pulse itself, plus 40 µs. Anything left over lands in the listening window as "spikes"
**on the stimulated side**. The game stimulates the side the pole leans toward, and spikes on that side push the cart toward the lean, which
is the correct move. So artifacts alone would make the system look like it plays well with no neurons at all: about 30–43 steps instead of
about 22 for coin flips. This has happened before: DishBrain's no-neuron control chips appeared to play until they changed how they hid
stimulation artifacts.

**Suggested solution.** `count_spikes(..., pulse_samples, mask_ms)` ignores every crossing on **every** electrode from the start of each pulse
until `mask_ms` after it. Use 3 ms until role 4 measures the real artifact length (week 2). Role 3 provides the pulse positions.

**How to test it works.** Unit test with planted spikes plus fake artifacts at known pulse times (a sharp jump followed by an exponential
decay back to zero):
- with the mask on, the artifacts aren't counted and real spikes outside the mask still are;
- with the mask off, the artifacts *are* counted, which proves the test can catch the bug.

---

## Fix 5: Uneven halves and ties (P16) · due Fri Oct 16 · about 30 min

**The bug.** `choose_action` in `feedback.py` compares raw totals: more spikes on electrodes 0–29 pushes left, more on 30–59 pushes right,
and a tie is a coin flip. Two problems follow.
- **Uneven halves:** real cultures are rarely balanced. If one half naturally fires twice as much, it wins almost every time, and the
  cart gets pushed one way (about 9 steps per game). DishBrain hit exactly this and had to add a correction.
- **Ties:** with few spikes per 100 ms, many windows tie, so many decisions are coin flips.

**Suggested solution.**
1. From made-up data, measure how often a 100 ms window ties at 1, 3 and 5 spikes per second per electrode, and put the table in your pull
   request.
2. Add an **optional, off-by-default** setting (`normalize_halves` in Ryan's config): before comparing, divide each half's count by that half's
   resting rate from the spontaneous recording.
3. Always log the raw counts. Later experiments need to see raw rates drift.

**How to test it works.** Unit tests:
- With normalization off, behavior is unchanged.
- With it on, a culture whose left half fires twice as much at rest no longer wins most windows by default.

---

## Fix 6: Check it on real data · due Fri Oct 23 (week 2) · about 1 h

**The bug.** Everything above is tested on made-up data only.

**Suggested solution.** Run the new detector on test day 1's recordings (from the shared drive, or through role 6's replay mode). There are
no neurons in those recordings, so **every spike reported is false**. Report false spikes per electrode per minute, both without stimulation
and with it (using role 3's pulse positions). Switch the artifact window to role 4's measured value once it's available.

**How to test it works.** Fewer than **1 false spike per electrode per minute** outside stimulation. With the test probe that's a meaningful
number. If the headstage was empty (no probe), the inputs were floating and the number may be poor; say so in your pull request, and we'll
re-test once we have probe or MEA data.

**Stretch (optional):** read about SALPA (Wagenaar & Potter, 2002), a way to *subtract* stimulation artifacts instead of ignoring a whole
window, and write half a page on how it would replace fix 4's mask. Background in `Experiment-Design-Notes.md` section 4.

## Done when
- All the unit tests above pass.
- The tie table and the real-data numbers are in your pull requests.
- Ryan has integrated the new detector.
