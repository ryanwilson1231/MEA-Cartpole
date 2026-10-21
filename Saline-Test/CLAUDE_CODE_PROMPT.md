# Instructions to paste into Claude Code

*Abbas, Oct 21, 2026*

**Setup:** unzip `Saline-Test.zip` into the root of your `MEA-Cartpole` clone so you have `MEA-Cartpole/Saline-Test/`. Open Claude Code in `MEA-Cartpole/` and paste PROMPT 1. Use PROMPT 2 only **after** the saline results are in.

---

## PROMPT 1: add the saline kit (tonight / before the test)

```
You are working in the MEA-Cartpole repo (Neurotech@Berkeley). I unzipped a new folder, Saline-Test/,
at the repo root. It was written and tested for me (Abbas) on Oct 21 2026 for our Oct 22 saline test.
Read Saline-Test/README.md, Saline-Test/CHANGES_abbas_2026-10-21.md and Saline-Test/TOMORROW_TEST_LIST.md
first, then do exactly this:

1. Create and switch to branch  abbas/2026-10-21-saline-kit  . Never commit to main; don't push unless I say so.
2. Do NOT edit anything in Baseline-Protocol/, Brian2-Path/, Hardware-Pythonnet-Path/, spike.py, square.py.
   The game must run unchanged tomorrow (we play it on saline as a control).
3. Archive my old file: move Baseline-Protocol/Hardware/Abbas_mea_device.py to
   Saline-Test/archive/abbas_2026-10-21_old_mea_device.py (it is untracked, so make sure it is not lost).
   Add this at the top of the archived file:
     # ARCHIVED by Abbas, Oct 21 2026 - not used, do not import.
     # Why: imports CMcsUsbBStimNet, which is not in our McsUsbNet.dll, so it cannot run.
     # Its two ideas live on: the 3 ms software blank -> Saline-Test/mea_kit/artifact_removal/blank_clean.py,
     # hardware blanking via CStg200xDownloadNet -> already in Baseline-Protocol/Hardware/mea_device.py.
4. Add to the repo .gitignore:  sessions/  and  *.bin  and  probe_report.txt   (recordings are ~7 GB - never commit them).
5. Add one row to the "Repo layout" table in the root README.md:
     | `Saline-Test/` | Saline test kit: artifact removers, saline benchmark (pivot table), UCSC-style mapping, saline stimulation protocol (Abbas, Oct 21 2026) |
6. Install and test (my laptop is a Mac, so pythonnet/hardware parts can't run here; that's expected):
     pip install -r Saline-Test/requirements.txt
     cd Saline-Test && python -m pytest -q tests
   All 22 tests must pass. If `salpa` fails to install on the Mac, try `xcode-select --install` then reinstall;
   if it still fails, say so and keep going (the kit falls back to a pure-Python remover). Don't rewrite tests to make them pass.
7. Dry run end to end and tell me the verdict table:
     python -m mea_kit.hardware.saline_protocol --dry-run --out ../sessions/dry --game-windows 40 --sweep-electrodes 0-5
     python -m mea_kit.saline_benchmark.run_benchmark --session ../sessions/dry
     python -m mea_kit.ucsc_mapping.run_mapping --session ../sessions/dry --version all
   Remember: dry-run data is FAKE (simulated device). It only proves the code runs.
8. Labeling rules for every file you add or change (from now on in this repo):
   - New file: a docstring/header that starts "Abbas, Oct 21 2026 (new)." followed by What it does and Why.
   - Changed file: add a dated line in its header "Abbas, Oct 21 2026 (changed): <what> - <why>" and keep
     the old behaviour mentioned if it matters.
   - Log every change in Saline-Test/CHANGES_abbas_2026-10-21.md under "What was added" or "Findings".
   - Commit messages: "[Abbas 2026-10-21] <short what> - <why>".
9. Commit in small steps (kit, archive, gitignore/README) and show me `git log --oneline` and `git status` at the end.
Do not touch any hardware, do not change stimulation amplitudes or safety limits in
Saline-Test/mea_kit/hardware/config.py, and ask me before anything that isn't on this list.
```

---

## PROMPT 2: after the saline results (do NOT run before)

```
Branch abbas/2026-10-22-apply-saline-results from abbas/2026-10-21-saline-kit.
Read sessions/<the real saline session>/benchmark/report.md, results.json, mapping/summary.md and
Saline-Test/CHANGES_abbas_2026-10-21.md ("Findings in the existing code"). Then propose - don't apply yet -
a plan for these changes to Baseline-Protocol/Hardware/, each with the saline evidence that justifies it:
  a) cathodic-first pulses in mea_device._pulse_train (swap the phase order)
  b) set the stimulation mode on BOTH generator channels (mea_device currently calls SetVoltageMode(0))
  c) current mode + the amplitude/width from the best saline row, if the table supports it
  d) plug in the winning artifact remover AND make the decoder ignore its blanked samples
     (Saline-Test/mea_kit/common/signal.py: masked_count_spikes)
  e) record the sideband stream + log pulse times in the game, and align the 100 ms decode window to the pulse
  f) if the electrode map says stim electrode k != recording channel k, fix LEFT/RIGHT_CHANNELS usage
  g) if the decoder was biased on saline, separate input electrodes from decoder zones (row R5 / mapping v3)
Keep feedback.py identical in Brian2/ and Hardware/ as its header requires. Same labeling rules as before.
Wait for my OK on the plan before editing.
```
