"""
Version 1: UCSC's mapping, as close to the paper as our rig allows. Abbas, Oct 21 2026 (new).

Phase 1 (record): spontaneous recording -> spikes at 5 x RMS per channel -> spike-triggered averages on
  other channels merge channels into unit "footprints" -> rank units by eta -> keep up to 32.
Phase 2 (stimulate): 50 biphasic pulses at 2 Hz per selected unit (our sweep block) -> response spikes at
  3 SD -> R[k,i,j] -> C1 (first-order, 10 ms methods / 18 ms figure), Cm (200 ms, bursts excluded),
  burst probability per stimulated unit.
Roles: UCSC picked 2 encoding + 2 decoding + 5-12 training units BY HAND with this rubric:
  strong input->output C1, Cm as tie-breaker, outputs that recruit broader activity, no burst-prone
  units; training units chosen independently of C1. We print the ranked candidates and a rubric-based
  suggestion so a person can still choose by hand, like UCSC did.
What it does NOT correct (that is version 2's job): background firing inflating C1, the blind period
right after the pulse, and multi-unit electrodes. On saline this version WILL report fake connections
from artifact and noise - that is the point of running it there.
"""
import numpy as np

from ..artifact_removal import get_remover
from .common_io import all_pulse_samples, pulses_by_electrode
from .scoring import burst_trials, c1_matrix, cm_matrix, detect_spikes, eta_scores, response_tensor
from ..common.signal import bandpass


def merge_footprints(rec, times, amps, sigma, frac=0.5, max_spikes=300):
    """Union channels whose spike-triggered average on another channel is >= frac of their own size.
    On our 200 um grid this should rarely merge anything (UCSC's grid is 17.5 um)."""
    chans = [c for c in times if len(times[c]) >= 5]
    parent = {c: c for c in chans}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    xf = {c: bandpass(rec.channel(c), rec.fs) for c in chans}
    for c in chans:
        t = times[c][:max_spikes]
        own = np.mean(amps[c][:max_spikes])
        for d in chans:
            if d == c:
                continue
            sta = -np.mean(xf[d][t]) / sigma[d]
            if sta >= frac * own:
                parent[find(d)] = find(c)
    groups = {}
    for c in chans:
        groups.setdefault(find(c), []).append(c)
    units = []
    for members in groups.values():
        best = max(members, key=lambda m: np.mean(amps[m]) if len(amps[m]) else 0)
        units.append({"unit": best, "members": sorted(members)})
    return units


def suggest_roles(C1, Cm, stims, units, burst_prob, rng, max_burst=0.2, n_train=(5, 12)):
    ok_in = [a for a, i in enumerate(stims) if burst_prob.get(i, 0) <= max_burst]
    best = None
    for a1 in ok_in:
        for a2 in ok_in:
            if a2 <= a1:
                continue
            for d1 in range(len(units)):
                for d2 in range(len(units)):
                    if d1 == d2 or units[d1] in (stims[a1], stims[a2]) or units[d2] in (stims[a1], stims[a2]):
                        continue
                    s = np.nan_to_num(C1[a1, d1]) + np.nan_to_num(C1[a2, d2])
                    tie = np.nan_to_num(Cm[a1, d1]) + np.nan_to_num(Cm[a2, d2])
                    key = (s, tie)
                    if best is None or key > best[0]:
                        best = (key, (stims[a1], stims[a2]), (units[d1], units[d2]))
    if best is None:
        return None
    used = set(best[1]) | set(best[2])
    rest = [u for u in units if u not in used]
    k = int(min(len(rest), rng.integers(n_train[0], n_train[1] + 1)))
    train = sorted(rng.choice(rest, k, replace=False).tolist()) if k else []
    return {"encoders": list(best[1]), "decoders": list(best[2]), "training_units": train,
            "score_c1": float(best[0][0]), "tiebreak_cm": float(best[0][1])}


def run(spont_rec, sweep_block, cleaner=None, cleaner_params=None, window_ms=10.0, max_units=32,
        thr_unit=5.0, thr_resp=3.0, cm_ms=200.0, seed=0, electrode_to_channel=None):
    rng = np.random.default_rng(seed)
    e2c = electrode_to_channel or {}
    c2e = {c: e for e, c in e2c.items()}
    # Phase 1
    times, amps, sigma = detect_spikes(spont_rec, thr_sd=thr_unit)
    eta = eta_scores(times, amps, spont_rec.duration_s)
    fp = merge_footprints(spont_rec, times, amps, sigma)
    ranked = sorted(fp, key=lambda u: -eta[u["unit"]]["eta"])
    ranked = [u for u in ranked if eta[u["unit"]]["active"]][:max_units]
    units = [u["unit"] for u in ranked]
    null_mode = False
    if not units:                       # saline / dead culture: nothing fires -> map every channel
        units = list(range(spont_rec.n_channels))
        null_mode = True
    # Phase 2
    pbe = pulses_by_electrode(sweep_block)
    stims = [u for u in units if c2e.get(u, u) in pbe]
    pulses_by_stim = {u: pbe[c2e.get(u, u)] for u in stims}
    rem = get_remover(cleaner) if cleaner else None
    st, _, _ = detect_spikes(sweep_block.rec, channels=units, thr_sd=thr_resp, cleaner=rem,
                             pulses=all_pulse_samples(sweep_block), cleaner_params=cleaner_params)
    fs = sweep_block.rec.fs
    out = {"version": "v1_ucsc_faithful", "null_mode": null_mode, "units": units, "stims": stims,
           "eta": {u: eta[u] for u in units}, "footprints": ranked}
    bursts, bthr = burst_trials(st, pulses_by_stim, units, fs, cm_ms)
    out["burst_threshold"] = bthr
    out["burst_prob"] = {i: float(np.mean(b)) for i, b in bursts.items()}
    for W in (10.0, 18.0):
        R = response_tensor(st, pulses_by_stim, units, fs, 0.0, W)
        C1 = c1_matrix(R, stims, units)
        for a, i in enumerate(stims):            # a unit's own electrode is not a connection
            C1[a, units.index(i)] = np.nan
        out[f"C1_{int(W)}ms"] = C1
    Rm = response_tensor(st, pulses_by_stim, units, fs, 0.0, cm_ms)
    out["Cm"] = cm_matrix(Rm, stims, units, bursts)
    C1 = out[f"C1_{int(window_ms)}ms"]
    out["roles_suggestion"] = suggest_roles(C1, out["Cm"], stims, units, out["burst_prob"], rng)
    out["n_pairs_c1_over_0.2"] = int(np.nansum(C1 > 0.2))
    return out
