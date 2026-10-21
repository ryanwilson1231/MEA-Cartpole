"""
What we measure for every (stimulation condition x artifact remover) cell. Abbas, Oct 21 2026 (new).

Saline has NO neurons, so the true answer is known: there are zero real spikes.
  1. blind period     ms after each pulse until the band-passed trace stays inside the spike
                      threshold (or the remover stops blanking). Shorter = we see neurons sooner.
                      (This is Syrine's "measure the blind period on each channel".)
  2. false spikes     threshold crossings after pulses (excess over the no-stim baseline rate).
                      Every one of them is fake on saline.
  3. spike recovery   "hybrid" test: we add fake spikes with KNOWN times/sizes into the saline
                      recording at 0.5-25 ms after pulses, run the remover, and count how many come
                      back (and how big). Saline can't tell us if a remover eats real spikes; this can.
  4. decoder bias     run the GAME's own decoder (count_spikes + choose_action from
                      Baseline-Protocol) on each stimulation window. With no neurons it should pick
                      the stimulated side 50% of the time. Much more than 50% = the artifact is
                      steering the game (and since the game stimulates the side the pole leans to,
                      artifact alone would push the cart the "right" way and fake learning).
Injected and non-injected windows are kept separate (half the windows each), so the fake spikes never
contaminate metrics 1, 2 and 4.
"""
import time

import numpy as np

from ..common.signal import bandpass, crossings, game_count_spikes, masked_count_spikes, spike_template, trough_after
from ..artifact_removal import get_remover
from ..common.pulses import group_key, estimate_hold_ms

THR_SD = 5.0
EPOCH_MAX_MS = 45.0
DELAY_BINS_MS = [(0.5, 2), (2, 5), (5, 10), (10, 25)]
INJECT_AMPS_SD = [6.0, 10.0, 16.0]


def wilson(k, n, z=1.96):
    if n == 0:
        return (np.nan, np.nan)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (c - h, c + h)


class BlockPlan:
    """Which pulses get fake spikes, which windows feed the decoder test."""

    def __init__(self, block, seed=0):
        rng = np.random.default_rng(seed)
        P = block.pulses
        self.samples = np.array([p["pulse_sample"] for p in P], dtype=np.int64)
        self.n = len(P)
        keys = [group_key(p) for p in P]
        uniq = {k: i for i, k in enumerate(dict.fromkeys(keys))}
        self.groups = np.array([uniq[k] for k in keys], int)
        # windows = pulses sharing one SendStart (game blocks) or single pulses
        sends = [p.get("sample_at_send") for p in P]
        wins = {}
        for i, s in enumerate(sends):
            wins.setdefault(s, []).append(i)
        self.windows = [sorted(v, key=lambda i: self.samples[i]) for _, v in sorted(wins.items())]
        inject_win = rng.random(len(self.windows)) < 0.5
        self.inject = np.zeros(self.n, bool)
        for w, flag in zip(self.windows, inject_win):
            if flag:
                self.inject[w] = True
        self.window_injected = inject_win
        nxt = np.r_[self.samples[1:], np.iinfo(np.int64).max]
        self.epoch_end = np.minimum(nxt, self.samples + int(EPOCH_MAX_MS * block.rec.fs / 1000))
        self.rng = rng


def stim_channel_sets(block):
    return [set(block.channels_of(p["electrodes"])) for p in block.pulses]


def make_injections(plan, fs, n_channels, n_samples):
    """Per channel list of (pulse_index, onset_sample, amp_sd, delay_ms)."""
    rng = plan.rng
    out = {c: [] for c in range(n_channels)}
    for i in np.flatnonzero(plan.inject):
        t0 = plan.samples[i]
        span_ms = (plan.epoch_end[i] - t0) / fs * 1000 - 2.5
        if span_ms < 1:
            continue
        for c in range(n_channels):
            d = rng.uniform(0.5, min(25.0, span_ms))
            a = INJECT_AMPS_SD[rng.integers(len(INJECT_AMPS_SD))]
            on = t0 + int(d * fs / 1000)
            if on + int(0.002 * fs) < n_samples:
                out[c].append((i, on, a, d))
    return out


class Accumulator:
    def __init__(self):
        self.blind = {"stim": [], "other": []}
        self.false = {"stim": [], "other": []}       # crossings per pulse
        self.epoch_ms = {"stim": [], "other": []}
        self.inj = []   # (cls, delay_ms, amp_sd, found, amp_ratio)
        self.win_counts = {}   # window index -> per-channel counts (decoder ignoring blanked samples)
        self.win_counts_asis = {}   # same, with the game's count_spikes exactly as it is today
        self.invalid_frac = []
        self.seconds = 0.0


def process_channel(block, plan, c, x_raw, sigma, remover, params, stimsets, inj_list, tmpl, acc, decoder_windows):
    fs = block.rec.fs
    x = x_raw.copy()
    raw_trough_gain = tmpl["gain"]
    for (i, on, a, d) in inj_list:
        w = tmpl["w"] * (a * sigma / raw_trough_gain)
        x[on: on + len(w)] += w[: len(x) - on]
    t = time.perf_counter()
    res = remover.clean_channel(x, fs, plan.samples, groups=plan.groups, **params)
    acc.seconds += time.perf_counter() - t
    xf = bandpass(res.x, fs)
    invalid = res.invalid if res.invalid is not None else np.zeros(len(xf), bool)
    acc.invalid_frac.append(float(invalid.mean()))
    valid = ~invalid
    thr = THR_SD * sigma
    # 1+2 on non-injected pulses
    for i in np.flatnonzero(~plan.inject):
        a, b = plan.samples[i], plan.epoch_end[i]
        if b <= a + 5:
            continue
        seg = np.abs(xf[a:b]) > thr
        seg |= invalid[a:b]
        hits = np.flatnonzero(seg)
        cls = "stim" if c in stimsets[i] else "other"
        acc.blind[cls].append((hits[-1] + 1) / fs * 1000 if len(hits) else 0.0)
        cr = crossings(xf[a:b], sigma, THR_SD, valid[a:b])
        acc.false[cls].append(len(cr))
        acc.epoch_ms[cls].append((b - a) / fs * 1000)
    # 3 hybrid recovery
    if inj_list:
        lo_all = min(plan.samples[i] for i, _, _, _ in inj_list)
        cr_all = crossings(xf, sigma, THR_SD, valid)
        cr_all = cr_all[cr_all >= lo_all - 10]
        tr_all = trough_after(xf, cr_all, fs)
        for (i, on, a, d) in inj_list:
            true_tr = on + tmpl["i_trough"]
            j = np.searchsorted(tr_all, true_tr - int(0.3e-3 * fs))
            found = j < len(tr_all) and abs(tr_all[j] - true_tr) <= int(0.3e-3 * fs)
            ratio = float(-xf[tr_all[j]] / (a * sigma)) if found else np.nan
            cls = "stim" if c in stimsets[i] else "other"
            acc.inj.append((cls, d, a, bool(found), ratio))
    # 4 decoder windows (non-injected only) -> the GAME's count_spikes on the cleaned window
    for wi, (start, stop) in decoder_windows.items():
        acc.win_counts.setdefault(wi, np.zeros(block.rec.n_channels, int))
        acc.win_counts_asis.setdefault(wi, np.zeros(block.rec.n_channels, int))
        seg = res.x[start:stop][None, :]
        acc.win_counts_asis[wi][c] = int(game_count_spikes(seg, fs)[0])
        acc.win_counts[wi][c] = int(masked_count_spikes(seg, fs, invalid[start:stop][None, :])[0])


def baseline_sigma(baseline_block, n_channels, max_s=30.0):
    """Per-channel noise (MAD of the game band-pass) from the no-stim block."""
    rec = baseline_block.rec
    stop = min(rec.n_samples, int(max_s * rec.fs))
    start = min(int(0.5 * rec.fs), stop // 4)
    sig = np.empty(n_channels)
    rate = np.empty(n_channels)
    for c in range(n_channels):
        xf = bandpass(rec.channel(c, start, stop), rec.fs)
        s = np.median(np.abs(xf)) / 0.6745
        sig[c] = s
        rate[c] = len(crossings(xf, s, THR_SD)) / ((stop - start) / rec.fs)
    return sig, rate


def fallback_sigma(block, plan, c, x):
    """Noise from samples > 120 ms after any pulse (only if there is no baseline block)."""
    fs = block.rec.fs
    m = np.ones(len(x), bool)
    for s in plan.samples:
        m[max(0, s - int(0.005 * fs)): s + int(0.12 * fs)] = False
    xf = bandpass(x, fs)
    v = xf[m] if m.sum() > fs * 0.5 else xf
    return float(np.median(np.abs(v)) / 0.6745)


def run_block(block, remover_names, sigma=None, base_rate=None, params=None, decoder_zones=None, seed=0,
              channels=None, progress=print):
    """Returns {remover: summary dict} for one block."""
    params = params or {}
    rec = block.rec
    fs = rec.fs
    chans = list(range(rec.n_channels)) if channels is None else list(channels)
    plan = BlockPlan(block, seed)
    stimsets = stim_channel_sets(block)
    inj = make_injections(plan, fs, rec.n_channels, rec.n_samples)
    w, itr = spike_template(fs)
    gain = float(-np.min(bandpass(np.r_[np.zeros(200), w, np.zeros(200)], fs)))
    tmpl = {"w": w, "i_trough": itr, "gain": gain}
    # decoder windows: predictable game windows that got NO fake spikes
    dec = {}
    win_meta = {}
    for wi, idx in enumerate(plan.windows):
        p0 = block.pulses[idx[0]]
        if plan.window_injected[wi] or p0.get("kind") not in ("predictable", "unpredictable"):
            continue
        start = int(plan.samples[idx[0]])
        stop = start + int((p0.get("window_ms") or 100) * fs / 1000)
        if stop <= rec.n_samples:
            dec[wi] = (start, stop)
            win_meta[wi] = p0.get("side") if p0.get("kind") == "predictable" else "both"
    # hardware-blanking hold length -> SALPA must stay "pegged" at least that long, or it tries to fit
    # the step where the hold releases and leaves a fake spike (seen in the Oct 21 dry run)
    stim_ch = sorted(set().union(*stimsets)) if stimsets else []
    hold_ms = estimate_hold_ms(rec, plan.samples, stim_ch) if len(plan.samples) else 0.0
    params = {k: dict(v) for k, v in params.items()}
    sp = params.setdefault("salpa", {})
    if sp.get("forcepeg_ms", "auto") == "auto":
        sp["forcepeg_ms"] = max(1.0, hold_ms + 0.3)
    out = {"_hold_ms": hold_ms}
    for name in remover_names:
        try:
            remover = get_remover(name)
        except Exception as e:  # noqa: BLE001
            out[name] = {"error": f"not available: {e}"}
            continue
        acc = Accumulator()
        t0 = time.perf_counter()
        for c in chans:
            x = rec.channel(c)
            s = sigma[c] if sigma is not None else fallback_sigma(block, plan, c, x)
            if not np.isfinite(s) or s <= 0:
                continue
            process_channel(block, plan, c, x, s, remover, params.get(name, {}), stimsets, inj.get(c, []), tmpl, acc, dec)
        out[name] = summarize(acc, win_meta, decoder_zones, base_rate, chans)
        out[name]["wall_s"] = round(time.perf_counter() - t0, 1)
        progress(f"    {block.name:16s} {name:15s} done in {out[name]['wall_s']} s")
    return out


def summarize(acc, win_meta, zones, base_rate, chans):
    s = {}
    for cls in ("stim", "other"):
        b = np.array(acc.blind[cls])
        s[f"blind_{cls}_median_ms"] = float(np.median(b)) if len(b) else np.nan
        s[f"blind_{cls}_p90_ms"] = float(np.percentile(b, 90)) if len(b) else np.nan
        f = np.array(acc.false[cls], float)
        ep = np.array(acc.epoch_ms[cls])
        expected = (np.nanmean(base_rate) * ep / 1000) if base_rate is not None and len(ep) else 0.0
        s[f"false_{cls}_per100"] = float(100 * np.mean(f - expected)) if len(f) else np.nan
        s[f"n_{cls}"] = int(len(b))
    inj = acc.inj
    if inj:
        arr = np.array([(1 if c == "stim" else 0, d, a, f, r) for c, d, a, f, r in inj], float)
        for cls_i, cls in ((1, "stim"), (0, "other")):
            for lo, hi in DELAY_BINS_MS:
                m = (arr[:, 0] == cls_i) & (arr[:, 1] >= lo) & (arr[:, 1] < hi) & (arr[:, 2] >= 10)
                s[f"recall_{cls}_{lo}-{hi}ms"] = float(arr[m, 3].mean()) if m.any() else np.nan
            m = (arr[:, 0] == cls_i) & (arr[:, 1] >= 2) & (arr[:, 1] < 10) & (arr[:, 2] >= 10)
            s[f"recall_{cls}_2-10ms"] = float(arr[m, 3].mean()) if m.any() else np.nan
            mm = m & (arr[:, 3] == 1)
            s[f"amp_ratio_{cls}"] = float(np.nanmedian(arr[mm, 4])) if mm.any() else np.nan
        m = (arr[:, 1] >= 2) & (arr[:, 1] < 10) & (arr[:, 2] >= 10)
        s["recall_all_2-10ms"] = float(arr[m, 3].mean()) if m.any() else np.nan
    s["invalid_frac"] = float(np.mean(acc.invalid_frac)) if acc.invalid_frac else np.nan
    s["compute_s"] = round(acc.seconds, 1)
    # decoder
    if acc.win_counts and zones:
        for tag, wc in (("", acc.win_counts), ("_asis", acc.win_counts_asis)):
            d = decoder_stats(wc, win_meta, zones)
            for k, v in d.items():
                s[k.replace("decoder_", "decoder" + tag + "_", 1) if tag else k] = v
    return s


def decoder_stats(win_counts, win_meta, zones):
    L, R = zones
    follow, n, diffs, unpred = 0.0, 0, [], []
    for wi, counts in win_counts.items():
        side = win_meta.get(wi)
        l, r = counts[L].sum(), counts[R].sum()
        act = "left" if l > r else ("right" if r > l else None)
        if side in ("left", "right"):
            n += 1
            follow += 1.0 if act == side else (0.5 if act is None else 0.0)
            diffs.append((l - r) * (1 if side == "left" else -1) / max(1.0, (l + r)))
        else:
            unpred.append(1.0 if act == "left" else (0.5 if act is None else 0.0))
    lo, hi = wilson(follow, n)
    return {"decoder_follow_rate": follow / n if n else np.nan, "decoder_follow_ci": (lo, hi), "decoder_n": n,
            "decoder_norm_diff": float(np.mean(diffs)) if diffs else np.nan,
            "decoder_unpredictable_left_rate": float(np.mean(unpred)) if unpred else np.nan}
