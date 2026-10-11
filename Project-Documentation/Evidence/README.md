# Evidence

Scripts behind the claims in `Pipeline-Review.md`. They run on any laptop (no MEA, no Windows, no DLL loading). Run from the repo root.

```bash
pip install numpy scipy gymnasium dnfile
python Project-Documentation/Evidence/check_dll_api.py
python Project-Documentation/Evidence/offline_checks.py
```

| File | What it shows |
|---|---|
| `check_dll_api.py` | Reads `McsUsbNet.dll`'s metadata and prints the real method signatures, parameter names and enum options. With no arguments it prints the classes our code uses; with a class name (e.g. `CStg200xBasicNet`) it prints all of that class's methods. Use it before writing any new DLL call. Backs P1, P2, P4, P5, P11, P23. |
| `McsUsbNet-API-reference.md` | The output of `check_dll_api.py`, saved for quick reading. Regenerate it if the DLL changes. |
| `offline_checks.py` | (1) The spike detector on pure noise and on planted spikes, and where its false spikes come from (P13). (2) The pulse trains sent to the stimulator: totals, 20 µs resolution, charge balance (P7). (3) Average CartPole episode lengths for stuck, coin-flip and reflex decision patterns, the reference table used to read results (P14, P19). |

These check the code as it was before round 1 (commit `dfb6cd4`). Once roles 5 and 6 land the new spike detector and the
`pytest` suite in `Baseline-Protocol/Hardware/tests/`, those tests take over; `offline_checks.py` section 1 describes the old detector.

Results when these were written (random numbers vary slightly between runs):
- Detector on pure noise: 0.15 false spikes per electrode per 100 ms window, 100% of them within 2 ms of a window edge.
- Detector on planted spikes: 133 planted, 138 reported; 54/60 electrodes exact.
- Pulse trains: 0 of 2,000 random trains had a bad total, an empty segment, or an off-grid duration.
- Episode lengths: stuck 9.4, coin flip 22.7, reflex 60% 29.5, reflex 75% 41.0, reflex 100% 42.7.
