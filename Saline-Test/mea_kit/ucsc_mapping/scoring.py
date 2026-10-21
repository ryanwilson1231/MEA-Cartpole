"""
Shared UCSC scoring. Abbas, Oct 21 2026 (new).

Definitions (from Robbins et al. via Syrine's notes):
  eta(unit)  = normalized log firing rate + normalized mean spike amplitude (ranks reliable units)
  R[k, i, j] = spike count on unit j in a post-stimulus window after repetition k of stimulating unit i
  C1[i, j]   = P(a pulse on i evokes >= 1 spike on j within W ms)  (W = 10 ms methods, 18 ms figure)
  Cm[i, j]   = mean spike count on j within ~200 ms, burst trials excluded
  burst      = trial whose total spike count over all units > median + 3 MAD (over trials)
"""
import numpy as np
from scipy.stats import binom

from ..common.signal import bandpass, crossings, trough_after


def detect_spikes(rec, channels=None, thr_sd=5.0, sigma=None, cleaner=None, pulses=None, cleaner_params=None):
    """Spike times (samples) and trough amplitudes (in noise SDs) per channel.
    If `cleaner` (a remover module) is given, it is applied first with `pulses`; its blanked samples
    can't hold spikes."""
    chans = range(rec.n_channels) if channels is None else channels
    times, amps, sig_out = {}, {}, {}
    for c in chans:
        x = rec.channel(c)
        valid = None
        if cleaner is not None and pulses is not None and len(pulses):
            r = cleaner.clean_channel(x, rec.fs, np.asarray(pulses), **(cleaner_params or {}))
            x = r.x
            valid = None if r.invalid is None else ~r.invalid
        xf = bandpass(x, rec.fs)
        s = sigma[c] if sigma is not None else float(np.median(np.abs(xf)) / 0.6745)
        cr = crossings(xf, s, thr_sd, valid)
        tr = trough_after(xf, cr, rec.fs)
        times[c] = tr
        amps[c] = -xf[tr] / s if len(tr) else np.array([])
        sig_out[c] = s
    return times, amps, sig_out


def eta_scores(times, amps, duration_s, min_rate_hz=0.1):
    chans = sorted(times)
    rate = np.array([len(times[c]) / duration_s for c in chans])
    amp = np.array([np.mean(amps[c]) if len(amps[c]) else 0.0 for c in chans])
    lr = np.log10(np.maximum(rate, 1e-3))

    def mm(v):
        return (v - v.min()) / (v.max() - v.min()) if v.max() > v.min() else np.zeros_like(v)

    eta = mm(lr) + mm(amp)
    active = rate >= min_rate_hz
    return {c: dict(rate_hz=float(r), mean_amp_sd=float(a), eta=float(e), active=bool(ac))
            for c, r, a, e, ac in zip(chans, rate, amp, eta, active)}


def count_in_window(spike_times, t0s, a, b):
    """Spike counts in [t0+a, t0+b) for each t0 (a, b in samples)."""
    st = np.asarray(spike_times)
    t0s = np.asarray(t0s)
    return np.searchsorted(st, t0s + b) - np.searchsorted(st, t0s + a)


def response_tensor(times, pulses_by_stim, units, fs, start_ms, stop_ms, start_by_unit=None):
    """R[i] = array (n_reps_i, n_units). start_by_unit: optional per (stim, unit) start in ms
    (e.g. after the measured blind period)."""
    R = {}
    for i, t0s in pulses_by_stim.items():
        M = np.zeros((len(t0s), len(units)), int)
        for jj, j in enumerate(units):
            a_ms = start_ms if start_by_unit is None else start_by_unit(i, j)
            M[:, jj] = count_in_window(times[j], t0s, int(a_ms * fs / 1000), int(stop_ms * fs / 1000))
        R[i] = M
    return R


def burst_trials(times, pulses_by_stim, units, fs, window_ms=200.0):
    """UCSC rule: a trial is a network burst if its total spike count (all units, 0-window_ms)
    exceeds median + 3 MAD over all trials. Returns {stim: bool array}, threshold."""
    tot = {}
    for i, t0s in pulses_by_stim.items():
        tot[i] = sum(count_in_window(times[j], t0s, 0, int(window_ms * fs / 1000)) for j in units)
    allv = np.concatenate([v for v in tot.values()]) if tot else np.array([])
    if allv.size == 0:
        return {}, np.nan
    med = np.median(allv)
    mad = np.median(np.abs(allv - med))
    thr = med + 3 * max(mad, 1.0)
    return {i: v > thr for i, v in tot.items()}, float(thr)


def c1_matrix(R, stims, units, exclude=None):
    C = np.full((len(stims), len(units)), np.nan)
    for a, i in enumerate(stims):
        m = R[i]
        if exclude is not None:
            m = m[~exclude[i]] if exclude.get(i) is not None and len(exclude[i]) == len(m) else m
        if len(m):
            C[a] = (m > 0).mean(axis=0)
    return C


def cm_matrix(R, stims, units, bursts):
    C = np.full((len(stims), len(units)), np.nan)
    for a, i in enumerate(stims):
        m = R[i]
        keep = ~bursts.get(i, np.zeros(len(m), bool))
        if keep.any():
            C[a] = m[keep].mean(axis=0)
    return C


def mcnemar_one_sided(post_hit, pre_hit):
    """Exact one-sided test that 'spike after the pulse' happens more than 'spike before the pulse'
    on the same trials. post_hit/pre_hit: bool arrays over trials."""
    b = int(np.sum(post_hit & ~pre_hit))
    c = int(np.sum(~post_hit & pre_hit))
    n = b + c
    if n == 0:
        return 1.0
    return float(binom.sf(b - 1, n, 0.5))


def bh_fdr(p, q=0.05):
    """Benjamini-Hochberg. p: array (nan ignored). Returns bool mask of discoveries."""
    p = np.asarray(p, float)
    ok = np.isfinite(p)
    out = np.zeros(p.shape, bool)
    pv = p[ok]
    if pv.size == 0:
        return out
    order = np.argsort(pv)
    m = pv.size
    thresh = q * (np.arange(1, m + 1) / m)
    passed = pv[order] <= thresh
    k = np.max(np.flatnonzero(passed)) + 1 if passed.any() else 0
    disc = np.zeros(m, bool)
    disc[order[:k]] = True
    out[ok] = disc
    return out
