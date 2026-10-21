"""
Side analyses for the saline report. Abbas, Oct 21 2026 (new).

  channel_health   are all 60 channels alive and recording through the session? (Syrine's step 3)
  electrode_map    from the sweep: which recording channel lights up when stimulating electrode k
                   (is stim electrode k == recording channel k, as feedback.py assumes?), and how far
                   each electrode's artifact spreads -> safe decoder zones for the moved-zones row
  amp_series       artifact size and blind period vs stimulation amplitude
  switch_test      can one generator hop to a new electrode every 5/10/20 ms? (re-route vs alternating)
"""
import numpy as np

from ..common.signal import bandpass, mad_sigma


def channel_health(block, max_s=30.0):
    rec = block.rec
    stop = min(rec.n_samples, int(max_s * rec.fs))
    rows = []
    for c in range(rec.n_channels):
        x = rec.channel(c, 0, stop)
        xf = bandpass(x, rec.fs)
        s = float(mad_sigma(xf))
        flat = float(np.mean(np.diff(x) == 0))
        rows.append({"channel": c, "label": rec.labels[c] if c < len(rec.labels) else str(c), "noise": s,
                     "dc": float(np.median(x)), "flat_frac": flat})
    med = np.median([r["noise"] for r in rows])
    for r in rows:
        r["status"] = ("DEAD/flat" if r["noise"] < 0.1 * med or r["flat_frac"] > 0.5 else
                       "noisy" if r["noise"] > 4 * med else "ok")
    return rows


def _post_peak(rec, c, samples, a_ms=1.5, b_ms=6.0):
    fs = rec.fs
    vals = []
    for s in samples:
        a, b = s + int(a_ms * fs / 1000), s + int(b_ms * fs / 1000)
        if b < rec.n_samples:
            seg = rec.channel(c, max(0, a - 400), b + 400)
            xf = bandpass(seg, fs)[400: 400 + (b - a)]
            vals.append(np.max(np.abs(xf)))
    return float(np.median(vals)) if vals else np.nan


def electrode_map(block, sigma):
    """Sweep block -> artifact matrix A[electrode, channel] in noise units, best channel per electrode."""
    rec = block.rec
    by_e = {}
    for p in block.pulses:
        if p.get("kind") == "sweep" and p["electrodes"]:
            by_e.setdefault(p["electrodes"][0], []).append(p["pulse_sample"])
    elecs = sorted(by_e)
    A = np.full((len(elecs), rec.n_channels), np.nan)
    for i, e in enumerate(elecs):
        smp = by_e[e][:6]
        for c in range(rec.n_channels):
            A[i, c] = _post_peak(rec, c, smp) / sigma[c]
    best = np.nanargmax(A, axis=1)
    srt = np.sort(A, axis=1)
    conf = srt[:, -1] / np.maximum(srt[:, -2], 1e-9)
    identity_ok = float(np.mean(best == np.array(elecs)))
    spread = {int(e): [int(c) for c in np.argsort(-A[i])[1:5]] for i, e in enumerate(elecs)}
    return {"electrodes": [int(e) for e in elecs], "A": A, "best_channel": [int(b) for b in best],
            "confidence": [float(x) for x in conf], "identity_fraction": identity_ok, "neighbors": spread,
            "electrode_to_channel": {int(e): int(b) for e, b in zip(elecs, best)}}


def suggest_zones(emap, left, right, inputs_left, inputs_right, k_exclude=4):
    """Decoder zones = each half minus the input electrodes' channels and their strongest-artifact neighbours."""
    e2c = emap.get("electrode_to_channel", {}) if emap else {}
    nb = emap.get("neighbors", {}) if emap else {}
    bad = set()
    for e in list(inputs_left) + list(inputs_right):
        bad.add(e2c.get(e, e))
        bad.update(nb.get(e, [])[:k_exclude])
    L = [c for c in left if c not in bad]
    R = [c for c in right if c not in bad]
    return np.array(L), np.array(R), sorted(bad)


def amp_series(block, sigma, remover_blind=None):
    rec = block.rec
    by = {}
    for p in block.pulses:
        by.setdefault(p.get("kind"), []).append(p)
    rows = []
    for kind, ps in sorted(by.items(), key=lambda kv: float(kv[1][0].get("amplitude") or 0)):
        e = ps[0]["electrodes"][0]
        c = block.channels_of([e])[0]
        smp = [p["pulse_sample"] for p in ps]
        fs = rec.fs
        peaks, blinds = [], []
        for s in smp:
            seg = rec.channel(c, max(0, s - 2000), min(rec.n_samples, s + int(0.05 * fs) + 2000))
            xf = bandpass(seg, fs)[2000: 2000 + int(0.045 * fs)]
            peaks.append(np.max(np.abs(xf)) / sigma[c])
            hits = np.flatnonzero(np.abs(xf) > 5 * sigma[c])
            blinds.append((hits[-1] + 1) / fs * 1000 if len(hits) else 0.0)
        rows.append({"kind": kind, "amplitude_nA": ps[0].get("amplitude"), "electrode": e, "channel": c,
                     "artifact_peak_sd": float(np.median(peaks)), "blind_ms_no_cleaning": float(np.median(blinds)),
                     "n": len(smp)})
    return rows


def switch_test(block, sigma):
    """Works from the sideband edges directly, because with spacing < latency jitter the pulses can
    come out in a different order than commanded. For each test kind (reroute_5ms, alternate_5ms, ...)
    we take the edges inside that kind's time range, find which channel lit up for each edge, and
    compare that sequence with the commanded electrode sequence."""
    from ..common.pulses import find_sideband_onsets
    rec = block.rec
    fs = rec.fs
    edges, why = find_sideband_onsets(rec, len(block.commands))
    if edges is None:
        edges = np.array(sorted(p["pulse_sample"] for p in block.pulses))
    kinds = {}
    for cmd in block.commands:
        kinds.setdefault(cmd["kind"], []).append(cmd)
    rows = []
    for kind, cmds in sorted(kinds.items(), key=lambda kv: (kv[0].split("_")[0], float(kv[0].split("_")[1][:-2]))):
        lo = min(c["sample_at_send"] for c in cmds)
        hi = max(c["sample_at_send"] for c in cmds) + int(0.1 * fs)
        ed = edges[(edges >= lo) & (edges < hi)]
        target = float(kind.split("_")[1][:-2])
        lit = []
        for s0 in ed:
            peaks = []
            for c in range(rec.n_channels):
                x = rec.channel(c, max(0, s0 - 400), min(rec.n_samples, s0 + int(0.004 * fs) + 400))
                xf = bandpass(x, fs)[400: 400 + int(0.004 * fs)]
                peaks.append(np.max(np.abs(xf)) / sigma[c] if len(xf) else 0.0)
            lit.append(int(np.argmax(peaks)))
        wanted = [block.channels_of(c["electrodes"])[0] for c in sorted(cmds, key=lambda c: c["sample_at_send"])]
        n = min(len(lit), len(wanted))
        right = float(np.mean([a == b for a, b in zip(lit[:n], wanted[:n])])) if n else np.nan
        gaps = np.diff(ed) / fs * 1000
        gaps = gaps[gaps < 3 * target + 50]
        cmd_ms = [float((c.get("route_ms") or 0) + (c.get("send_ms") or 0)) for c in cmds]
        rows.append({"kind": kind, "target_ms": target, "commanded": len(cmds), "pulses_seen": int(len(ed)),
                     "achieved_gap_median_ms": float(np.median(gaps)) if len(gaps) else np.nan,
                     "achieved_gap_p10_p90_ms": (float(np.percentile(gaps, 10)), float(np.percentile(gaps, 90))) if len(gaps) else None,
                     "command_ms_median": float(np.median(cmd_ms)), "right_electrode_in_order": right})
    return rows
