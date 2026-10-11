# Experiment Design Notes

Input for **round 2 and later**: the meeting with Prof. Feldman (UC Berkeley), what the DishBrain and UCSC papers did, and the controls
we'll need before claiming learning.

**Round 1 doesn't run any of these experiments.** Its job is to prove the current baseline pipeline works (`Round-1.md`). But round 1
should **log the data these controls need**, because adding logging later means redoing sessions. Each section ends with what round 1
needs to record.

---

## 1. Feldman meeting: what was said and what it means

The meeting notes mix Feldman's comments with our prepared questions. His points, one at a time:

### 1.1 "Observe firing rates over time of all the electrodes"
**What he meant:** we record from all 60 electrodes all the time, not just the ones that decide the action. So we can watch every
electrode's firing rate across a session and across days, and see *net* changes in the network.
**Why it matters:** this is the most direct way to see homeostasis (the network turning its overall activity up or down to
compensate), as opposed to task-specific change.
**Round 1 records:** per-electrode spike counts every step (not just left/right totals), plus a spontaneous recording before and after
each session. Both are in the round-1 logging spec (`Pipeline-Review.md` P17, P18).

### 1.2 "A reward is typically a neuromodulator"
**What he meant:** in the brain, reinforcement works through neuromodulators like dopamine. A dopamine pulse strengthens *whatever
activity patterns were active in the few seconds before it*. That's reinforcement: credit goes to recent activity.
**Why it matters:** our cultures have no dopamine system. Our "reward" (predictable stimulation) is just more electrical stimulation, not
a neuromodulator. DishBrain's framework is about *predictability* (cultures avoid unpredictable input), not reward in the dopamine sense.
We should avoid calling predictable stimulation a "reward" in write-ups unless we mean it loosely. A literal reward signal would mean
delivering a neuromodulator, which is a different experiment.

### 1.3 "The right control: the high-frequency stimulus at randomly chosen times, the same number of times"
**What he meant:** to show a stimulus works *as feedback*, compare against a control where the culture gets the same stimulus, the same
number of times, but at random moments unrelated to what it did.
**Why it matters:** the stimulus itself changes the network (more activity, plasticity, homeostasis) whether or not it's tied to
behavior. Only the timing should differ between conditions. The UCSC paper's "random" condition is close to this; DishBrain's
"no-feedback" condition is another version.
**Round 1 records:** the full stimulation schedule (every pulse's time, side and type). A later control session can replay the same
amount in shuffled order.

### 1.4 "Good controls give the same amount of good and bad stimulation but randomize the timing"
**What he meant:** match the *dose* of each stimulus type (predictable and unpredictable) between experiment and control, and only
change whether the timing depends on performance.
**Why it matters:** in our design, a culture that plays well gets more predictable stimulation and less unpredictable. Any difference
between good and bad cultures could come from that different dose, not from learning. Our prepared question about the UCSC group
(training stimulation only when performance drops, so worse dishes get more of it) is the same concern.
**Round 1 records:** stimulation dose per electrode per session (pulse counts by type and side), computed from the schedule log.

### 1.5 "We can strongly change the physics to see if an adaptation occurs"
**What he meant:** learning is goal-directed, and we control the game. Change the rules sharply mid-session (pole length, gravity, push
force, or flip which population means left) and see whether performance drops and then recovers.
**Why it matters:** homeostasis doesn't track a goal, so it shouldn't re-adapt to a rule change. Learning should. This is the same idea
as our planned decoder swap.
**Round 1 records:** nothing extra. But the round-1 code should make physics settings and the left/right decoder mapping configurable,
so round 2 doesn't need surgery.

### 1.6 Optical stimulation
**What he meant (our reading of the notes):** with light-activated neurons (optogenetics), the light's effect on the electrodes
(the photoelectric artifact) lasts nanoseconds, so you can record immediately after the light turns off. Electrical stimulation artifacts
last much longer. But getting cells to express light-sensitive proteins takes a lot of optimization.
**Why it matters:** it's a future way around the artifact problem (`Pipeline-Review.md` P14). Our hardware already supports it: the SCU
has four outputs for LED-driven optical stimulation (manual pp. 6–7, 24).
**When:** much later, and only with the wet-lab group that supplies our neurons.

### 1.7 Answers on timescales (from our prepared question)
We asked which would show up first under patterned stimulation: short-term depression, stronger inhibition, or synaptic scaling.

| Mechanism | Timescale (Feldman) | What it means for us |
|---|---|---|
| Short-term plasticity | appears within about 10 ms, lasts briefly | Within a stimulation train, later pulses may evoke smaller responses than the first. Pulse spacing matters; our predictable stimulus is 2 pulses 50 ms apart. |
| Long-term depression (LTD) | can be induced by trains of activity over minutes | Within a single 15–20 minute session, the stimulated pathways can weaken. A performance change within a session could be LTD rather than learning. |
| Synaptic scaling (homeostatic) | gradually, over many hours | Matters across sessions and days. Compare spontaneous rates before and after sessions, limit stimulation hours per day, and include rest. |

### 1.8 Our prepared questions that still need answers
The notes don't record answers to these. Ask them in the follow-up (the plan was to email Feldman a one-page design summary, and to
ask whether he or someone in his lab could give periodic feedback):
1. What fraction of the culture is GABAergic (inhibitory), and the minimum to learn about the cells before running anything? Ask the
   wet-lab group too.
2. Could the UCSC dose-tied-to-performance design look like learning through homeostasis? Is their random condition enough?
3. Does homeostasis act locally enough to shift the balance between our left and right halves? Which way of evening out stimulation
   would he trust: mirror-symmetric layouts, compensating stimulation during rest, or comparing only dose-matched conditions?
4. Is a flat left/right ratio enough evidence against rate drift? Is a single decoder swap clean? Is yoked replay to a different dish
   too noisy compared with the same dish on another day?
5. Are our planned readouts right (spontaneous before/after, a fixed stimulation test before/after, dose per electrode, policy quality)?

---

## 2. What the two published studies did

| | DishBrain (Kagan et al., *Neuron*, 2022) | UCSC organoids (Robbins et al., *Cell Reports*, 2026) |
|---|---|---|
| Hardware | MaxOne HD-MEA, 1,024 recording channels, 20 kHz | MaxOne HD-MEA, 20 kHz |
| Neurons | Rodent and human cortical cultures, 2D | Mouse cortical organoids, 3D |
| Task | Pong | CartPole (pole terminal angle ±16°, no track limits) |
| Input electrodes | 8 sensory electrodes, separate from output | 2 input units, separate from output and training units |
| Encoding | Place (which of 8) + rate 4–40 Hz, 75 mV | Rate only, about 0.8–8.9 Hz, 200 µs per phase |
| Decoding | Spike counts in two motor regions, every 10 ms, with gain toward 20 Hz | Smoothed rate (α = 0.2) of 2 output units, 200–300 ms windows |
| Feedback / training | Hit: 75 mV, 100 Hz, 100 ms. Miss: 150 mV, 5 Hz, random sites, 4 s | High-frequency patterns on separate training units, only at episode end, only when the 5-episode mean < 20-episode mean |
| Artifact handling | "Command count blinding": ignore all activity whenever a stimulation command is sent | SALPA artifact subtraction, then 3σ threshold |
| Session structure | 20 min sessions (analysed as 0–5 and 6–20 min); 3 sessions/day for 3 days in the feedback study | 15 min training cycles, 45 min rest; up to 48 h continuous |
| Controls | Media-only MEAs (no cells), non-neural HEK293T cells, rest (no sensory input), in-silico random, silent feedback, no feedback | Null (no training), random training, pharmacology (NBQX + APV blocks learning, washout restores it), in-silico random proficiency threshold |
| Key result | Within-session improvement; not robust across days | Adaptive training beat random and null; gains didn't survive the 45 min rest |

**Lessons that apply to us:**
1. **Artifacts fooled DishBrain's first controls.** Their no-cell controls showed apparent performance until they changed how they hid
   stimulation artifacts. Our no-cell runs (test probe now, a saline MEA once we have a spare) exist to catch this
   (`Pipeline-Review.md` P14).
2. **Keep input and output electrodes separate** before claiming learning. Both studies did; our baseline doesn't (P19). Layout v2
   (bottom row in, top row out) is being built in round 1 so round 2 can use it.
3. **Uneven activity pins the decoder**, so DishBrain added a gain (P16).
4. **Improvements were short-lived** in both: within-session, gone after rest. Plan analyses within sessions first.
5. **Inanimate materials can "improve" too.** UCSC cites a study where hydrogels in a Pong setup improved. Controls without neurons aren't
   optional.

---

## 3. Controls roadmap (round 2 and later)

Combining Feldman's advice, our prepared plan, and the two papers. Each control rules out one alternative explanation.

| Control | Rules out | Precedent | What round 1 must log so it's possible |
|---|---|---|---|
| **No-cell runs** (test probe, saline / media-only MEA), repeated | Artifacts or electronics producing "performance" | DishBrain media-only MEAs; hydrogel study | Full step logs (built in round 1); first runs once we have a spare MEA |
| **Repetition**: several cultures, several sessions each | One lucky dish or session | Both papers | Session metadata (culture ID, DIV, MEA ID) |
| **Dose-matched, timing-randomized stimulation** | Effects of the amount of stimulation itself | Feldman; UCSC random; DishBrain no-feedback | Stimulation schedule, dose per electrode |
| **Yoked replay**: play one session's exact stimulation to another dish (or the same dish another day), independent of its behavior | Homeostatic and other non-task effects of that exact stimulation | Our plan | Stimulation schedule with pulse timing |
| **Decoder swap / physics change** mid-session | One population just getting louder | Our plan; Feldman 1.5 | Configurable decoder mapping and physics |
| **Rest / spontaneous-only play** | Performance from spontaneous activity alone | DishBrain rest sessions | `spontaneous` mode; closed loop with stimulation off |
| **Population balance tracking**: left/right ratio and per-electrode rates before, during, after | Simple rate drift | Our plan; Feldman 1.1 | Per-electrode counts, spontaneous before/after |
| **Fixed stimulation test before and after** each session | Changes in responsiveness unrelated to the task | UCSC stimulation phase; our plan | `stim_check` mode |
| **Policy quality**: does the action correct for the pole's lean, not just how long the pole stays up | Long episodes by luck | UCSC policy plots; our plan | Angle and action per step |
| **Pharmacology** (block glutamate receptors) | Non-synaptic explanations | UCSC NBQX + APV | Wet-lab dependent; much later |

---

## 4. SALPA (artifact removal)

**What it is:** Subtraction of Artifacts by Local Polynomial Approximation (Wagenaar & Potter, *J. Neurosci. Methods*, 2002). After each
stimulation pulse, the electrode signal relaxes slowly back to baseline. SALPA fits a low-order polynomial to a short sliding window of
the signal, which follows the slow relaxation but not fast spikes, and subtracts it. Spikes riding on the tail survive. That recovers
activity much sooner after a pulse than simply ignoring a window. It runs in real time; the UCSC group used it on every read period.

**Why later:** round 1 hides artifacts by ignoring a short window after each pulse, which is simple and safe. SALPA is worth it once we
need responses in the first few milliseconds (evoked-response analysis, the separate input/output layout in round 2).

**What round 1 should do so SALPA is easy later:** save raw data around stimulation on the test days. That's exactly the data needed
to prototype SALPA offline and compare it with simply ignoring a window. Role 5 can read the paper as a stretch goal
(`Round-1-Tasks/T5-spike-detection.md`).
