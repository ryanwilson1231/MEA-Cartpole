# Project Documentation

Everything about how the MEA CartPole project works, what's wrong with it right now, and what we're doing about it.

**New here? Read in this order:**
1. `Round-1.md`: what this round is for, the seven roles (pick one), and the schedule.
2. `System-Overview.md`: what the project is and how one game step works.
3. Your role's doc in `Round-1-Tasks/`: every bug you'll fix, with a suggested solution and how to test it.
4. For the full technical background on any problem (P-numbers), `Pipeline-Review.md`.

**Questions or stuck for more than 2 hours? Message Kai.**

| File | What it's for |
|---|---|
| [Round-1.md](Round-1.md) | **Start here.** This round's goals, the seven roles, schedule and deadlines, how we work |
| [Round-1-Tasks/](Round-1-Tasks/) | One doc per role (T1–T7): every bug as *the bug → suggested solution → how to test it*, with deadlines |
| [Test-Day-Run-Sheet.md](Test-Day-Run-Sheet.md) | The step-by-step checklist for the hardware test days (Oct 18 and Oct 25), with a results table |
| [System-Overview.md](System-Overview.md) | The project in one paragraph, the hardware, one game step from start to end, how to read episode lengths, code map, settings specific to our setup |
| [Pipeline-Review.md](Pipeline-Review.md) | Every known problem (P1–P23) in detail: where, why, what you'd see, how to fix, how to prove it's fixed |
| [Experiment-Design-Notes.md](Experiment-Design-Notes.md) | Round 2 and later: Feldman meeting takeaways, what DishBrain and UCSC did, controls roadmap, SALPA |
| [Evidence/](Evidence/) | Scripts behind the review's claims; re-run them any time |
| [References/](References/) | Source papers, our poster, and (locally) the hardware manual; see below |

## References

All in `References/`.

| File | What it is | Most useful parts |
|---|---|---|
| `dishbrain-pong-kagan-2022.pdf` (+ `.txt`) | Kagan et al., "In vitro neurons learn and exhibit sentience when embodied in a simulated game-world", *Neuron* 110 (2022). [doi:10.1016/j.neuron.2022.09.001](https://doi.org/10.1016/j.neuron.2022.09.001). Open access, CC BY. | STAR Methods (PDF pp. 22–25): stimulation settings, artifact "blinding", electrode layout, feedback types, controls |
| `organoid-cartpole-cell-reports.txt` | Robbins et al., "Goal-directed learning in cortical organoids", *Cell Reports* 45 (2026). [doi:10.1016/j.celrep.2026.116984](https://doi.org/10.1016/j.celrep.2026.116984). Open access, CC BY 4.0. Article text only; read it with figures at the DOI link. | Training paradigm, rate coding, SALPA, controls, sessions with rest periods |
| `MEA-poster-2026.png` | Our 2026 poster | What we've presented publicly so far |
| `MCS_MEA2100-Mini-System-manual.pdf` | MCS user manual for our hardware. **Not in git:** MCS doesn't allow redistribution. Download it from multichannelsystems.com into this folder. | Components (pp. 6–9), software and PC requirements (pp. 10–11), MEA orientation (p. 13), test probe (p. 13), filter settings (pp. 15–16), troubleshooting (pp. 18–19), specs (pp. 21–22) |

The `.txt` files are plain-text copies for searching and for AI tools. Files in this folder that git ignores (see `.gitignore`): the MCS
manual and any saved publisher web pages.

## Conventions
- Problems are referred to as **P1–P23** everywhere. The numbers are defined in `Pipeline-Review.md`.
- When a fix is merged or a test-day check passes, update the docs in the same pull request: fill in the settings table in
  `System-Overview.md`, and note the fix next to its problem in `Pipeline-Review.md`.
