"""
Version 3: automatic role selection on top of version 2. Abbas, Oct 21 2026 (new).

UCSC chose inputs/outputs by hand and listed that as a limitation. Here: try every ordered pair of input
electrodes (A drives the LEFT zone, B the RIGHT zone; ~60x59 = 3,540 ordered pairs), and score
    contrast_j = C1sig(A->j) - C1sig(B->j)      (C1sig = baseline-corrected C1, 0 if not significant)
    fixed zones:   score = mean contrast over the left zone - mean contrast over the right zone
    learned zones: left zone = the k channels A drives most over B, right zone = the reverse
Input electrodes that trigger bursts or have long artifacts are dropped, and decoder-zone channels must
not be the inputs or their artifact neighbours (Syrine: never put decoder zones right next to inputs).
"""
import itertools

import numpy as np


def run(v2, zones="fixed", left=None, right=None, neighbors=None, electrode_to_channel=None, k=4,
        exclude_inputs=(), top_n=10, min_score=0.0):
    e2c = electrode_to_channel or {}
    nb = neighbors or {}
    W = v2["chosen_window_ms"]
    res = v2[f"W{int(W)}"]
    C = np.where(res["significant"], np.nan_to_num(res["C1corr"]), 0.0)
    stims, units = v2["stims"], v2["units"]
    col = {u: b for b, u in enumerate(units)}
    bad_in = set(v2.get("bursty_inputs", [])) | set(exclude_inputs)
    cand = [e for e in stims if e not in bad_in]
    rows = {e: a for a, e in enumerate(stims)}
    scored = []
    for A, B in itertools.permutations(cand, 2):
        banned = {e2c.get(A, A), e2c.get(B, B)} | set(nb.get(A, [])) | set(nb.get(B, []))
        cvec = C[rows[A]] - C[rows[B]]
        if zones == "fixed":
            L = [col[c] for c in (left or []) if c in col and c not in banned]
            R = [col[c] for c in (right or []) if c in col and c not in banned]
            if not L or not R:
                continue
            score = float(np.mean(cvec[L]) - np.mean(cvec[R]))
            zl, zr = [units[i] for i in L], [units[i] for i in R]
        else:
            ok = [i for i, u in enumerate(units) if u not in banned]
            if len(ok) < 2 * k:
                continue
            order = sorted(ok, key=lambda i: -cvec[i])
            Lz, Rz = order[:k], order[-k:]
            if np.min(cvec[Lz]) <= 0 or np.max(cvec[Rz]) >= 0:
                continue
            score = float(np.mean(cvec[Lz]) - np.mean(cvec[Rz]))
            zl, zr = [units[i] for i in Lz], [units[i] for i in Rz]
        if score > min_score:
            scored.append({"input_left": A, "input_right": B, "score": score, "zone_left": zl, "zone_right": zr})
    scored.sort(key=lambda d: -d["score"])
    return {"version": "v3_auto_select", "zones": zones, "window_ms": W, "candidates": scored[:top_n],
            "best": scored[0] if scored else None, "n_pairs_scored": len(scored),
            "excluded_inputs": sorted(bad_in)}
