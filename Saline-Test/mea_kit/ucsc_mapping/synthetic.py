"""
Fake culture with KNOWN connections, to check the mapping code. Abbas, Oct 21 2026 (new).

Background firing per electrode, true stimulus->response pairs at 3-8 ms latency, one "bursty" input
that sometimes sets off a dish-wide burst, and a decaying artifact after every pulse. Small by default
(24 channels, 20 kHz) so tests run in seconds.
"""
import numpy as np

from ..common.recording import Recording
from ..common.signal import spike_template


class SimpleBlock:
    def __init__(self, rec, pulses, name="sweep"):
        self.rec, self.pulses, self.name = rec, pulses, name
        self.e2c = None

    def channels_of(self, electrodes):
        return sorted(electrodes)


def _rec(data, fs):
    return Recording(fs, data.shape[0], data.shape[1], lambda c, a=0, b=None: data[c, a:b])


def make_culture(n_ch=24, fs=20000, spont_s=40.0, stim_electrodes=(2, 5, 9, 14, 18, 21), reps=40, rate_hz=4.0,
                 n_true=10, p_resp=0.7, bursty=9, p_burst=0.35, noise=6.0, artifact=400.0, seed=0, active=None):
    rng = np.random.default_rng(seed)
    w, itr = spike_template(fs)
    active = set(range(n_ch)) if active is None else set(active)
    rates = {c: (rng.uniform(0.5, 4.0) if c in active else 0.0) for c in range(n_ch)}
    amp = {c: rng.uniform(10, 16) * noise for c in range(n_ch)}

    def add_spike(x, c, t):
        if 0 <= t < x.shape[1] - len(w):
            x[c, t: t + len(w)] -= amp[c] * w   # template trough is -1 -> negative spike

    # spontaneous
    n0 = int(spont_s * fs)
    spont = rng.normal(0, noise, (n_ch, n0))
    for c in range(n_ch):
        for t in rng.uniform(0, n0, rng.poisson(rates[c] * spont_s)).astype(int):
            add_spike(spont, c, t)
    # true connections (stim electrode -> target channel)
    pairs = set()
    stims = list(stim_electrodes)
    while len(pairs) < n_true:
        i = stims[rng.integers(len(stims))]
        j = int(rng.integers(n_ch))
        if j != i and j in active and abs(j - i) > 1:
            pairs.add((i, j))
    # sweep
    gap = int(fs / rate_hz)
    n1 = len(stims) * reps * gap + gap
    sweep = rng.normal(0, noise, (n_ch, n1))
    for c in range(n_ch):
        for t in rng.uniform(0, n1, rng.poisson(rates[c] * n1 / fs)).astype(int):
            add_spike(sweep, c, t)
    tk = np.arange(int(0.03 * fs)) / fs * 1000
    pulses = []
    t = gap // 2
    for i in stims:
        for k in range(reps):
            pulses.append({"pulse_sample": t, "electrodes": [i], "kind": "sweep", "side": "", "mode": "current",
                           "amplitude": 10000, "phase_us": 200, "sample_at_send": t})
            for c in range(n_ch):
                d = abs(c - i)
                a = artifact * (1.0 if d == 0 else 0.25 / d ** 1.5)
                sweep[c, t: t + len(tk)] += a * np.exp(-tk / 0.6) * (1 if c % 2 else -1)
            for (a_, j) in pairs:
                if a_ == i and rng.random() < p_resp:
                    add_spike(sweep, j, t + int(rng.uniform(3, 8) * fs / 1000))
            if i == bursty and rng.random() < p_burst:
                for c in range(n_ch):
                    for tt in t + rng.uniform(int(0.01 * fs), int(0.15 * fs), 8).astype(int):
                        add_spike(sweep, c, tt)
            t += gap
    return {"spont": _rec(spont, fs), "sweep": SimpleBlock(_rec(sweep, fs), pulses), "true_pairs": sorted(pairs),
            "bursty": bursty, "rates": rates}
