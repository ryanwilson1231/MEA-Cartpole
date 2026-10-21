"""
Drift check. Abbas, Oct 21 2026 (new).

A culture's connections change on their own (weights drift), so a before/after difference is not proof
of learning (Wagenaar et al. 2006: changes after stimulation were often no bigger than drift).
Plan: map twice BEFORE training (map A, map B) -> natural drift; map once AFTER (map C).
A pair only counts as changed by training if |C - B| is bigger than both its own drift |B - A| and the
95th percentile of drift over all pairs.
"""
import numpy as np


def _mat(m):
    W = m["chosen_window_ms"]
    return np.asarray(m[f"W{int(W)}"]["C1corr"], float)


def compare(map_a, map_b, map_c=None):
    A, B = _mat(map_a), _mat(map_b)
    ok = np.isfinite(A) & np.isfinite(B)
    drift = np.abs(B - A)
    out = {"drift_corr": float(np.corrcoef(A[ok], B[ok])[0, 1]) if ok.sum() > 2 else np.nan,
           "drift_mean_abs": float(np.nanmean(drift[ok])) if ok.any() else np.nan,
           "drift_p95": float(np.nanpercentile(drift[ok], 95)) if ok.any() else np.nan}
    if map_c is not None:
        Cc = _mat(map_c)
        ok2 = ok & np.isfinite(Cc)
        change = np.abs(Cc - B)
        beyond = ok2 & (change > drift) & (change > out["drift_p95"])
        out.update({"after_mean_abs_change": float(np.nanmean(change[ok2])) if ok2.any() else np.nan,
                    "pairs_changed_beyond_drift": [(int(i), int(j)) for i, j in zip(*np.nonzero(beyond))],
                    "n_changed_beyond_drift": int(beyond.sum()), "n_pairs": int(ok2.sum())})
    return out
