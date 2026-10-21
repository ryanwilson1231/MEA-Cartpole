"""
Turn the hardware's stimulation command log into exact pulse onset samples.

Abbas, Oct 21 2026 (new).
Why: every metric is measured relative to the pulse onset, so the onset must be right to
~0.1 ms. The software log only knows roughly when SendStart() was called (USB latency is
several ms), so we refine it from the data, in this order of preference:
  1. sideband / digital stream bit that is high while the stimulator is active (exact)
  2. the artifact itself on the stimulated electrodes (a jump, or the flat run that hardware
     blanking leaves behind)
"""
import numpy as np

from .signal import hf_sigma


def _rising_edges(v):
    v = np.asarray(v).astype(np.int64)
    return np.flatnonzero((v[1:] != 0) & (v[:-1] == 0)) + 1


def find_sideband_onsets(rec, expected_n, first_analog_free_stream=None, tol=0.25):
    """Search the non-analog streams bit by bit for one whose rising edges match the number of
    pulses we expect. Returns (onset_samples, description) or (None, reason)."""
    if rec.n_streams <= rec.n_channels:
        return None, "no extra streams recorded"
    start = first_analog_free_stream if first_analog_free_stream is not None else rec.n_channels
    best = None
    for s in range(start, rec.n_streams):
        v = rec.stream(s)
        if not np.any(v):
            continue
        vv = v.astype(np.int64) & 0xFFFFFFFF
        for b in list(range(32)) + ["any"]:
            bit = (vv != 0).astype(np.int64) if b == "any" else (vv >> b) & 1
            if not bit.any():
                continue
            edges = _rising_edges(bit)
            if len(edges) == 0:
                continue
            err = abs(len(edges) - expected_n) / max(expected_n, 1)
            if best is None or err < best[0]:
                best = (err, s, b, edges)
    if best is None or best[0] > tol:
        return None, f"no stream/bit with ~{expected_n} rising edges (best err {None if best is None else round(best[0], 2)})"
    return best[3], f"stream {best[1]} bit {best[2]} ({len(best[3])} edges for {expected_n} expected)"


def _first_artifact(rec, channels, lo, hi, k=25.0, flat_run=6):
    """First sample in [lo, hi) where any of `channels` jumps by > k * its step-noise, or starts a
    run of >= flat_run identical samples (hardware blanking hold)."""
    lo, hi = max(0, lo), min(rec.n_samples, hi)
    if hi - lo < 4:
        return None
    first = None
    for c in channels:
        x = rec.channel(c, lo, hi)
        d = np.abs(np.diff(x))
        s = hf_sigma(rec.channel(c, max(0, lo - 5000), lo)) if lo > 100 else hf_sigma(x)
        s = s * np.sqrt(2.0) if s > 0 else (np.median(d) + 1e-9)
        hits = np.flatnonzero(d > k * s)
        cand = hits[0] + 1 if len(hits) else None
        same = d == 0
        if same.any():
            run = np.convolve(same.astype(int), np.ones(flat_run, int), "valid")
            flats = np.flatnonzero(run == flat_run)
            if len(flats) and (cand is None or flats[0] < cand):
                cand = flats[0]
        if cand is not None and (first is None or cand < first):
            first = cand
    return None if first is None else lo + int(first)


def refine_from_commands(rec, commands, electrode_to_channel=None, search_before_ms=20.0, search_after_ms=400.0,
                         match_tol_ms=1.0, max_latency_ms=100.0):
    """commands: rows from <block>_commands.csv (one row per generator per SendStart) with keys
    sample_at_send, onsets_us (list), electrodes (list) + metadata.
    Rows sharing a sample_at_send were sent together (e.g. both sides in an unpredictable window).
    Returns (pulse rows sorted by time, description). Each pulse row has 'pulse_sample' and
    'source' = 'sideband' | 'artifact' | 'log'."""
    fs = rec.fs
    e2c = electrode_to_channel or {}
    groups = {}
    for c in commands:
        groups.setdefault(int(c["sample_at_send"]), []).append(c)
    sends = sorted(groups)
    expected = []   # (send, offset_samples, command, k)
    for s0 in sends:
        rows = groups[s0]
        on_min = min(min(c["onsets_us"]) for c in rows)
        for c in rows:
            for k, on in enumerate(c["onsets_us"]):
                expected.append((s0, int(round((on - on_min) * fs / 1e6)), c, k))
    n_exp = len(expected)
    edges, why = find_sideband_onsets(rec, n_exp)
    out = []
    if edges is not None:
        tol = int(match_tol_ms * fs / 1000)
        max_lat = int(max_latency_ms * fs / 1000)
        by_send = {}
        for s0, off, c, k in expected:
            by_send.setdefault(s0, []).append((off, c, k))

        def n_match(t_first, offs):
            hits = 0
            for off in offs:
                g = t_first + off
                j = np.searchsorted(edges, g - tol)
                hits += int(j < len(edges) and edges[j] <= g + tol)
            return hits

        # pass 1: for each send, the first-pulse edge that explains the most of its pulse pattern
        best = {}
        for s0 in sends:
            offs = [o for o, _, _ in by_send[s0]]
            lo, hi = np.searchsorted(edges, s0 - int(1e-3 * fs)), np.searchsorted(edges, s0 + max_lat)
            cands = [(n_match(int(edges[i]), offs), int(edges[i])) for i in range(lo, hi)]
            best[s0] = cands
        full = [min(e for h, e in cs if h == max(h2 for h2, _ in cs)) - s0 for s0, cs in best.items() if cs]
        med = float(np.median(full)) if full else 0.0
        # pass 2: among the best-explaining candidates, take the one closest to the typical latency
        used = set()
        matched = 0
        for s0 in sends:
            cs = best[s0]
            if not cs:
                continue
            top = max(h for h, _ in cs)
            t_first = min((e for h, e in cs if h == top), key=lambda e: abs((e - s0) - med))
            for off, c, k in sorted(by_send[s0], key=lambda z: z[0]):
                g = t_first + off
                j = np.searchsorted(edges, g)
                cand = [int(edges[i]) for i in (j - 1, j, j + 1) if 0 <= i < len(edges) and int(edges[i]) not in used]
                b = min(cand, key=lambda e: abs(e - g)) if cand else None
                if b is not None and abs(b - g) <= tol:
                    used.add(b)
                    out.append(_row(c, k, b, "sideband"))
                    matched += 1
        if matched >= 0.9 * n_exp:
            out.sort(key=lambda r: r["pulse_sample"])
            return out, f"sideband: {why}; matched {matched}/{n_exp}; median latency {med / fs * 1000:.1f} ms"
        why = f"sideband matched only {matched}/{n_exp}"
        out = []
    for s0 in sends:
        rows = groups[s0]
        chans = sorted({e2c.get(e, e) for c in rows for e in c["electrodes"]})[:8] or list(range(min(8, rec.n_channels)))
        lo = s0 - int(search_before_ms * fs / 1000)
        hi = s0 + int(search_after_ms * fs / 1000)
        first = _first_artifact(rec, chans, lo, hi)
        src = "artifact"
        if first is None:
            first, src = s0, "log"
        for c in rows:
            on_min = min(min(cc["onsets_us"]) for cc in rows)
            cch = [e2c.get(e, e) for e in c["electrodes"]][:8] or chans
            for k, on in enumerate(c["onsets_us"]):
                guess = first + int(round((on - on_min) * fs / 1e6))
                if src == "artifact" and guess != first:
                    g2 = _first_artifact(rec, cch, guess - int(0.5e-3 * fs), guess + int(2e-3 * fs))
                    guess = g2 if g2 is not None else guess
                out.append(_row(c, k, guess, src))
    out.sort(key=lambda r: r["pulse_sample"])
    return out, "artifact-based (" + why + ")"


def _row(c, k, sample, src):
    r = {key: c.get(key) for key in ("cmd_index", "kind", "side", "electrodes", "generator", "mode",
                                       "amplitude", "phase_us", "polarity", "window_ms", "sample_at_send",
                                       "route_ms", "send_ms")}
    r["pulse_sample"] = int(sample)
    r["pulse_in_cmd"] = k
    r["window_start_sample"] = None
    r["source"] = src
    return r


def group_key(p):
    """Pulses that should share an artifact template: same electrodes, mode, amplitude, phase."""
    return (p.get("side"), p.get("mode"), p.get("amplitude"), p.get("phase_us"), tuple(p.get("electrodes") or ()))


def estimate_hold_ms(rec, pulse_samples, channels, max_ms=5.0, n_pulses=40):
    """How long the hardware blanking holds the signal flat after a pulse (median over pulses and
    stimulated channels). Returns 0.0 if there is no flat run (e.g. blanking off)."""
    fs = rec.fs
    L = int(max_ms * fs / 1000)
    runs = []
    for s0 in list(pulse_samples)[:n_pulses]:
        for c in list(channels)[:6]:
            x = rec.channel(c, s0, min(rec.n_samples, s0 + L))
            if len(x) < 3:
                continue
            same = np.diff(x) == 0
            # longest run of identical samples that starts within the first 0.3 ms
            best = 0
            i = 0
            while i < len(same):
                if same[i]:
                    j = i
                    while j < len(same) and same[j]:
                        j += 1
                    if i <= int(0.3e-3 * fs):
                        best = max(best, j - i + 1)
                    i = j
                else:
                    i += 1
            runs.append(best)
    if not runs:
        return 0.0
    med = float(np.median(runs))
    return med / fs * 1000 if med >= 3 else 0.0
