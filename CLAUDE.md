# MEA CartPole

Neurons on a 60-electrode MCS MEA2100-Mini play CartPole: stimulation tells them which way the pole leans, and their spikes decide which
way to push the cart. Neurotech@Berkeley MEA team.

## Where things are
- **Active code:** `Baseline-Protocol/Hardware/` (Python + pythonnet + `McsUsbNet.dll`). The hardware parts only run on the Windows
  computer connected to the MEA (currently Ryan's laptop). `Hardware-Pythonnet-Path/`, `Brian2-Path/` and the root `spike.py` /
  `square.py` are old code that doesn't run; they're moving to `archive/`.
- **Documentation:** `Project-Documentation/`. Start with `Project-Documentation/README.md`.
  - The current round (goals, roles, deadlines) is `Round-1.md`; each role's work is in `Round-1-Tasks/`.
  - Known problems are P1–P23 in `Pipeline-Review.md`; hardware facts and the code map are in `System-Overview.md`.
  - Source papers are in `References/`; read the `.txt` copies. The MCS hardware manual is only there if someone downloaded it (it's
    not in git).

## Rules for working in this repo
- Before writing or changing any call into `McsUsbNet.dll`, check the real signature with
  `python Project-Documentation/Evidence/check_dll_api.py`, or read `Evidence/McsUsbNet-API-reference.md`. Wrong calls only fail at
  runtime on the Windows computer, on a test day, so guessing is expensive.
- The DLL can't load on Mac or Linux. To test hardware code on a laptop, stub the .NET modules the way
  `Project-Documentation/Evidence/offline_checks.py` does, or use `fake_mea_device.py` once role 6 adds it.
- Round 1 (Oct 11–25) is code fixes, tested on the hardware on Oct 18 and Oct 25. Every round-1 test uses the current baseline design;
  layout v2 (role 1) is built alongside it as an option. Other design ideas go in `Project-Documentation/Experiment-Design-Notes.md`.
- When a fix lands, update the matching doc (`System-Overview.md` settings table, `Pipeline-Review.md`) in the same change.
- Don't commit the MCS manual (redistribution not allowed), saved publisher web pages, or session data (`sessions/`).
