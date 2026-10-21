"""
Simple blanking. Abbas, Oct 21 2026 (new).

What: after every pulse, throw away `blank_ms` of data (replace it with the pre-pulse baseline,
and mark it invalid so no spike can be detected there).
Why: this is the idea from Abbas_mea_device.py (STIM_BLANK_MS = 3, "ignore spikes for 3 ms
after each stim"). It is the simplest possible fix, so it is the baseline every smarter method
has to beat. The benchmark tells us whether 3 ms is long enough on our rig.
Note: filling with 0 would create a step (our raw data has a DC offset) that rings through the
band-pass filter and makes FAKE spikes. Even a flat baseline fill leaves a step where the blank ends
(the artifact tail is still there), so the default ramps linearly from the pre-pulse baseline to the
first sample after the blank. The decoder must also ignore the blanked samples (masked_count_spikes).
"""
import numpy as np
from .base import CleanResult, baseline_fill_value

DEFAULTS = {"blank_ms": 3.0, "pre_ms": 0.1, "fill": "linear"}  # fill: linear (ramp, no step) | baseline (flat)


def check_available():
    return True


def clean_channel(x, fs, pulses, groups=None, blank_ms=3.0, pre_ms=0.1, fill="linear", **_):
    y = np.asarray(x, dtype=np.float64).copy()
    n = len(y)
    invalid = np.zeros(n, bool)
    pre, post = int(pre_ms * fs / 1000), int(blank_ms * fs / 1000)
    for t0 in pulses:
        a, b = max(0, t0 - pre), min(n, t0 + post)
        if a >= b:
            continue
        v0 = baseline_fill_value(x, a, fs)
        if fill == "linear" and b < n:
            v1 = float(np.median(x[b: min(n, b + int(0.5e-3 * fs) + 1)]))
            y[a:b] = np.linspace(v0, v1, b - a)
        else:
            y[a:b] = v0
        invalid[a:b] = True
    return CleanResult(y, invalid, {"method": "blank", "blank_ms": blank_ms, "fill": fill})
