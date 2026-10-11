# Round 1: make the pipeline trustworthy (Oct 11 – Oct 25)

## What this round is

Our code for playing CartPole with neurons on the MEA (`Baseline-Protocol/Hardware/`) has never run on the real hardware. When we
checked it, we found it would crash on startup. Past that, there are smaller bugs that would make any results untrustworthy:
- stimulation that isn't the same on both sides,
- spike counts that include fake spikes,
- timing that drifts,
- almost nothing saved.

**Round 1 fixes those bugs.** It's code only: no cells and no MEA dish. Every test uses the current design; the next design (layout v2,
role 1) is built alongside it as an option. Everyone works on their own laptop for a week.
Then we connect the hardware to Ryan's computer, run everyone's checks, and record data. Everyone finishes using that data, and we test once
more two weeks from now.

**Questions or stuck for more than 2 hours? Message Kai.**

## Goals: what fixing all this gets us

1. **It runs.** The program starts, runs a full session and shuts down cleanly on the real hardware, every time, without anyone power-cycling
   anything.
2. **We can trust what we record.** Every sample arrives with nothing dropped and nothing invented, in real units (microvolts), lined up with
   the exact moment each stimulation pulse fired.
3. **We stimulate exactly what we intend.** Both sides get identical pulses, nothing outside safe limits can ever be sent, and every pulse is
   written down.
4. **Spike counts are real spikes.** No fake spikes from the math, no double counts, no stimulation artifacts counted as neural activity.
5. **Everyone can work without the hardware.** A fake MEA and automatic tests let you build and check your code on a Mac.
6. **Every run explains itself.** Each session saves a complete record, and one report shows at a glance whether the system behaved.
7. **The next design is ready to try.** Layout v2 stimulates the bottom row of electrodes and reads decisions from the top row, so the
   neurons have to carry the signal across the dish. It's built, tested on the fake device, and run once on the hardware, ready for round 2.


**What "done" looks like on Sunday Oct 25:** on Ryan's computer with the hardware connected, one command runs a full session (recording with
no stimulation → stimulation check → the game → recording again). It finishes without errors, every check in `Test-Day-Run-Sheet.md` passes,
and the session's report is generated automatically.

## The seven roles

Roles 1 and 2 are the co-leads. **Roles 3–7 are open: pick the one that sounds most like you.** Each role's doc in `Round-1-Tasks/` lists
every bug you'd fix, in the same format:
- **the bug:** what the code does now, and why it's a problem;
- **the suggested solution:** with code;
- **how to test it works:** on your laptop, and on test day.

### 1. Coordination, repo and layout v2 (Kai, co-lead) · about 13 hours plus oversight
Keeps the round on track and is the person to message when you're stuck. Kai cleans up the repository before anyone starts, archiving old
code that can't run, and splits the main hardware file into three so people don't overwrite each other's work. He asks the hardware
manufacturer (MCS) the questions only they can answer, hosts both test days with the hardware, and writes up what each person needs to fix.

He also builds **layout v2**, the next encoding/decoding design:
- the pole's lean picks the left or right three electrodes on the bottom row;
- its angular velocity sets the pulse rate;
- the action is read from the left and right three electrodes on the top row.

Because input and output electrodes are separate, the system can no longer win just because the stimulated electrodes respond. That's the
design both published studies used. [Details](Round-1-Tasks/T1-coordination-and-repo.md)

### 2. Integration (Ryan, co-lead) · 9–10 hours
Owns the main program, `run_hardware.py`, and the computer it runs on. Ryan defines the function names everyone codes against. He makes
the program start and stop reliably even when something goes wrong, and moves all settings into one file that gets saved with every run. He
adds the session modes we'll need later: recording with no stimulation, a stimulation check, and timed game sessions. He also sets up his
Windows laptop to drive the hardware, and runs the computer on both test days. [Details](Round-1-Tasks/T2-integration.md)

### 3. Recording · 9 hours · at both test days
Everything about getting data *out* of the MEA. Right now recording crashes during setup because the code calls a library function
Python isn't allowed to use. Even after that's fixed, the code:
- ignores most of the data streams the hardware sends,
- pads missing samples with zeros,
- never converts to microvolts,
- and can't tell which samples came right after a stimulation pulse.

You'd fix all of that, then write the scripts that prove it on test day. This is careful, detail-oriented work with a hardware library: you
read function signatures and data layouts closely. **Good fit if** you like getting low-level details exactly right and want hands-on time with
the hardware. [Details](Round-1-Tasks/T3-recording.md)

### 4. Stimulation · 9 hours · at both test days
Everything about sending pulses *into* the culture. Today:
- the code never checks that the stimulator connected,
- only one of the two stimulus generators is set to the right mode, so left and right could get physically different pulses,
- nothing stops an unsafe setting from being sent,
- nothing records which pulses were actually delivered.

You'd fix those, add a map of which electrode is which, and write the scripts that check the stimulator on test day. In week 2 you'd use the
recordings to confirm the stimulator played exactly what we sent. **Good fit if** you're comfortable debugging hardware code and like knowing
exactly what a system is physically doing. This is the trickiest of the open roles. [Details](Round-1-Tasks/T4-stimulation.md)

### 5. Spike detection · 8 hours · laptop only
Turns raw voltages into spike counts, which is what decides every move in the game. The current detector invents about 1.5 fake spikes per
second on every electrode, as many as a real culture produces at rest. It can also count one spike twice, lets bursts of activity shift its
own threshold, and can't tell a stimulation artifact from a neuron. You'd rebuild it (the suggested fix is already tested and removes
>99% of the fake spikes) and write tests. In week 2 you'd run it on the real recordings. **Good fit if** you like signal processing, numpy/scipy,
or data science. [Details](Round-1-Tasks/T5-spike-detection.md)

### 6. Fake device and tests · 7 hours · laptop only
Makes it possible for everyone to work without the hardware. You'd build a fake MEA that behaves like the real one: random spikes, and
optionally the failure modes we worry about, such as an unbalanced culture or stimulation artifacts. Your fake device is due **Wednesday**,
because everyone else tests their code on it. You'd also set up the automatic test suite and pin package versions. In week 2 you'd add a
replay mode that feeds the test-day recordings through the code as if the hardware were connected. **Good fit if** you like software
engineering, testing, and building tools other people rely on. [Details](Round-1-Tasks/T6-fake-device-and-tests.md)

### 7. Logging and analysis · 8 hours · laptop only
Makes every run leave a complete record and turns it into a report. Right now the program saves only how long each game lasted. Nothing
records:
- the pole angles,
- the actions,
- the spike counts,
- the stimulation,
- or the settings used.

You'd build the session logger, then a notebook that reports the results against known reference levels and warns automatically when
something looks wrong, such as a stuck decoder or artifacts driving the game. **Good fit if** you like data analysis, plotting, and
explaining results clearly. [Details](Round-1-Tasks/T7-logging-and-analysis.md)

## Schedule

| Date | Due |
|---|---|
| Mon Oct 12 | Repo access for everyone, cleanup, main file split (Kai) |
| Tue Oct 13 | Shared function names (Ryan); log format agreed (role 7 with Ryan) |
| Wed Oct 14 | Ryan's computer set up; fake device ready (role 6); 15-minute check-in |
| **Fri Oct 16** | **Everyone: pull request open.** Week-1 fixes done, tests pass, works on the fake device, test-day check script written. |
| **Sat Oct 17** | **Everything merged.** Ryan does a dry run on the fake device. |
| **Sun Oct 18** | **Test day 1** on Ryan's computer: run every check, record data (Ryan, Kai, roles 3 and 4 there; others on call) |
| Mon Oct 19 | Data on the shared drive; results and per-person fix lists posted (Kai) |
| Wed Oct 21 | 15-minute check-in |
| **Fri Oct 23** | **Everyone: pull request open** with test-day fixes and week-2 work, tested on the recorded data |
| **Sat Oct 24** | Everything merged; dry run on the recorded data |
| **Sun Oct 25** | **Test day 2**: full session on the hardware, plus one layout v2 run |

About two-thirds of everyone's hours fall in week 1.

## How we work

- **One branch per role, small pull requests,** reviewed by Kai or Ryan.
- **Only code that talks to the hardware needs Ryan's computer.** The MCS library (`McsUsbNet.dll`) and its USB driver are Windows-only, and
  the hardware has to be plugged in. Everything else runs on a Mac.
- **Check before you call.** Before writing any call into the MCS library, look up its real signature in
  `Evidence/McsUsbNet-API-reference.md` (or run `Evidence/check_dll_api.py`). A wrong call only fails on test day.
- **Don't commit recorded data.** It's about 12 MB per second; it lives on the shared drive.
- **Stuck for 2 hours? Message Kai.**

## More detail

- `System-Overview.md`: the hardware, and how one game step works.
- `Round-1-Tasks/`: one doc per role, every bug with solution and test.
- `Test-Day-Run-Sheet.md`: the test-day checklist.
- `Pipeline-Review.md`: the full technical write-up of every problem (P1–P23), with sources.
