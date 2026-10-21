"""
Template subtraction. Abbas, Oct 21 2026 (new).

What: line up every pulse of the same kind, take the MEDIAN artifact across repeats (median,
not mean, so a real spike in one repeat doesn't leak into the template), and subtract it.
Each epoch is baseline-corrected first so subtracting never introduces a DC step.
Why: Syrine's backup method. It is simple and keeps all the data (no blanking).
Weak spot: it assumes every artifact of a group has the SAME shape. On saline that is nearly true,
so it will look better on saline than it will on cells (a real neural response rides on the tail
and shifts the shape). Read its saline score as an upper bound.
`groups`: pulses with the same group id share a template (same electrodes/amplitude/width).
`mode="running"` uses only the previous `running_n` pulses (what you could do online, in real time).
"""
import numpy as np

from .base import CleanResult, next_pulse_limits

DEFAULTS = {"post_ms": 45.0, "pre_ms": 1.0, "min_repeats": 8, "mode": "all", "running_n": 20, "fit_scale": False}


def check_available():
    return True


def clean_channel(x, fs, pulses, groups=None, post_ms=45.0, pre_ms=1.0, min_repeats=8, mode="all",
                  running_n=20, fit_scale=False, **_):
    x = np.asarray(x, dtype=np.float64)
    y = x.copy()
    n = len(x)
    pulses = np.asarray(pulses, dtype=np.int64)
    if len(pulses) == 0:
        return CleanResult(y, None, {"method": "template", "groups": 0})
    groups = np.zeros(len(pulses), int) if groups is None else np.asarray(groups)
    ends = next_pulse_limits(pulses, n, fs, post_ms)
    pre = int(pre_ms * fs / 1000)
    skipped = 0
    Lmax = int(post_ms * fs / 1000)
    for g in np.unique(groups):
        idx = np.flatnonzero(groups == g)
        idx = idx[(pulses[idx] - pre >= 0)]
        if len(idx) < min_repeats:
            skipped += len(idx)
            continue
        # every epoch keeps its OWN length (until its next pulse), so one short gap can't shrink the template
        lens = np.minimum(ends[idx] - pulses[idx], Lmax)
        ep = np.full((len(idx), Lmax), np.nan)
        for j, i in enumerate(idx):
            L = int(lens[j])
            if L > 0:
                ep[j, :L] = x[pulses[i]: pulses[i] + L] - np.median(x[pulses[i] - pre: pulses[i]])
        count = np.sum(np.isfinite(ep), axis=0)
        with np.errstate(all="ignore"):
            full_tmpl = np.nanmedian(ep, axis=0)
        full_tmpl[count < min_repeats] = np.nan    # not enough repeats this far out: don't subtract
        for j, i in enumerate(idx):
            L = int(lens[j])
            if L <= 0:
                continue
            if mode == "running":
                lo = max(0, j - running_n)
                if j - lo < min_repeats // 2:
                    continue
                with np.errstate(all="ignore"):
                    tmpl = np.nanmedian(ep[lo:j, :L], axis=0)
            else:
                tmpl = full_tmpl[:L]
            tmpl = np.where(np.isfinite(tmpl), tmpl, 0.0)
            a = 1.0
            if fit_scale:
                seg = np.nan_to_num(ep[j, :L])
                den = float(np.dot(tmpl, tmpl))
                a = float(np.dot(seg, tmpl) / den) if den > 0 else 1.0
            y[pulses[i]: pulses[i] + L] -= a * tmpl
    return CleanResult(y, None, {"method": "template", "groups": 0})
    groups = np.zeros(len(pulses), int) if groups is None else np.asarray(groups)
    ends = next_pulse_limits(pulses, n, fs, post_ms)
    pre = int(pre_ms * fs / 1000)
    skipped = 0
    for g in np.unique(groups):
        idx = np.flatnonzero(groups == g)
        idx = idx[(pulses[idx] - pre >= 0)]
        if len(idx) < min_repeats:
            skipped += len(idx)
            continue
        L = int(np.min(ends[idx] - pulses[idx]))  # common epoch length inside this group
        if L < 5:
            continue
        ep = np.stack([x[pulses[i]: pulses[i] + L] - np.median(x[pulses[i] - pre: pulses[i]]) for i in idx])
        if mode == "running":
            for j, i in enumerate(idx):
                lo = max(0, j - running_n)
                if j - lo < min_repeats // 2:
                    continue  # not enough history yet: leave as is
                tmpl = np.median(ep[lo:j], axis=0)
                y[pulses[i]: pulses[i] + L] -= tmpl
        else:
            tmpl = np.median(ep, axis=0)
            for j, i in enumerate(idx):
                a = 1.0
                if fit_scale:
                    den = float(np.dot(tmpl, tmpl))
                    a = float(np.dot(ep[j], tmpl) / den) if den > 0 else 1.0
                y[pulses[i]: pulses[i] + L] -= a * tmpl
    return CleanResult(y, None, {"method": "template", "mode": mode, "groups": int(len(np.unique(groups))),
                                 "pulses_without_template": int(skipped)})
