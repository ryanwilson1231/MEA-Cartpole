"""
Version 2: UCSC mapping adapted to OUR rig (Syrine's adaptations 1-4). Abbas, Oct 21 2026 (new).

1. Electrode = unit. Our electrodes are 200 um apart and hear a small group of neurons, so we skip
   footprint merging and map regions ("area around electrode 14 drives area around 37").
   With 60 electrodes we can stimulate every active one (UCSC had to choose 32).
2. Background firing. A multi-unit electrode fires a lot on its own, so some spikes after a pulse would
   have happened anyway. We count spikes in the same-length window just BEFORE each pulse, report
   C1corr = C1(after) - C1(before), and test every pair with an exact one-sided test on the same trials,
   then Benjamini-Hochberg FDR across all ~3,500 pairs.
3. Window. C1 is computed at 10 ms (UCSC methods) and 18 ms (UCSC figure); the window with more
   FDR-significant pairs is used (both are reported).
4. Blind period. The window starts after the blind period (from the saline benchmark) instead of at 0,
   and the stimulated electrode itself is never scored.
Bursts: UCSC's rule (total spikes > median + 3 MAD) removes burst trials before testing; electrodes whose
pulses often trigger bursts are flagged as bad inputs.
On saline (no neurons) this version should find ~0 significant pairs - the null test.
"""
import numpy as np

from ..artifact_removal import get_remover
from .common_io import all_pulse_samples, pulses_by_electrode
from .scoring import bh_fdr, burst_trials, cm_matrix, count_in_window, detect_spikes, eta_scores, mcnemar_one_sided, response_tensor


def run(spont_rec, sweep_block, cleaner="salpa", cleaner_params=None, windows=(10.0, 18.0), blind_ms=2.0,
        thr_sd=5.0, q=0.05, cm_ms=200.0, max_burst=0.2, guard_ms=0.5, electrode_to_channel=None, sigma=None):
    e2c = electrode_to_channel or {}
    fs = sweep_block.rec.fs
    n = sweep_block.rec.n_channels
    times0, amps0, _ = detect_spikes(spont_rec, thr_sd=thr_sd, sigma=sigma)
    eta = eta_scores(times0, amps0, spont_rec.duration_s)
    units = [c for c in range(n) if eta[c]["active"]]
    null_mode = False
    if len(units) < 2:
        units, null_mode = list(range(n)), True
    pbe = pulses_by_electrode(sweep_block)
    stims = [e for e in sorted(pbe) if e2c.get(e, e) in units or null_mode]
    pulses_by_stim = {e: pbe[e] for e in stims}
    rem = get_remover(cleaner) if cleaner else None
    st, _, _ = detect_spikes(sweep_block.rec, channels=units, thr_sd=thr_sd, sigma=sigma, cleaner=rem,
                             pulses=all_pulse_samples(sweep_block), cleaner_params=cleaner_params)
    bursts, bthr = burst_trials(st, pulses_by_stim, units, fs, cm_ms)
    bprob = {e: float(np.mean(b)) for e, b in bursts.items()}

    def start_ms(e, j):
        b = blind_ms(e, j) if callable(blind_ms) else blind_ms
        return float(b)

    out = {"version": "v2_ours_adapted", "null_mode": null_mode, "units": units, "stims": stims,
           "burst_prob": bprob, "burst_threshold": bthr, "bursty_inputs": [e for e, p in bprob.items() if p > max_burst],
           "eta": {u: eta[u] for u in units}}
    best = None
    for W in windows:
        C1p = np.full((len(stims), len(units)), np.nan)
        C1b = np.full_like(C1p, np.nan)
        P = np.full_like(C1p, np.nan)
        for a, e in enumerate(stims):
            t0s = pulses_by_stim[e]
            keep = ~bursts.get(e, np.zeros(len(t0s), bool))
            t0s = t0s[keep]
            if len(t0s) < 5:
                continue
            for b, j in enumerate(units):
                if j == e2c.get(e, e):
                    continue
                s = start_ms(e, j)
                L = W - s
                if L <= 0.5:
                    continue
                post = count_in_window(st[j], t0s, int(s * fs / 1000), int(W * fs / 1000)) > 0
                pre = count_in_window(st[j], t0s, -int((L + guard_ms) * fs / 1000), -int(guard_ms * fs / 1000)) > 0
                C1p[a, b] = post.mean()
                C1b[a, b] = pre.mean()
                P[a, b] = mcnemar_one_sided(post, pre)
        sig = bh_fdr(P, q)
        res = {"C1_post": C1p, "C1_pre": C1b, "C1corr": C1p - C1b, "p": P, "significant": sig,
               "n_significant": int(sig.sum()), "n_tested": int(np.isfinite(P).sum())}
        out[f"W{int(W)}"] = res
        if best is None or res["n_significant"] > out[f"W{int(best)}"]["n_significant"]:
            best = W
    out["chosen_window_ms"] = best
    Rm = response_tensor(st, pulses_by_stim, units, fs, 0.0, cm_ms)
    out["Cm"] = cm_matrix(Rm, stims, units, bursts)
    return out
