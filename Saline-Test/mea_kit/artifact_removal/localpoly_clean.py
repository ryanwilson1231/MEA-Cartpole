"""
SALPA-like local cubic fit in pure Python. Abbas, Oct 21 2026 (new).

What: after each pulse, blank `blank_ms`, then fit a sliding cubic (Savitzky-Golay, half-width
`halfwidth_ms`) to the rest of the post-pulse segment and subtract it.
Why: only a FALLBACK if `pip install salpa` fails on a laptop (e.g. no compiler on a Mac). It is NOT
SALPA (no saturation state machine, offline only); the report labels it separately.
"""
import numpy as np
from scipy.signal import savgol_filter

from .base import CleanResult, baseline_fill_value, next_pulse_limits

DEFAULTS = {"halfwidth_ms": 2.0, "blank_ms": 1.0, "post_ms": 45.0}


def check_available():
    return True


def clean_channel(x, fs, pulses, groups=None, halfwidth_ms=2.0, blank_ms=1.0, post_ms=45.0, **_):
    x = np.asarray(x, dtype=np.float64)
    y = x.copy()
    n = len(x)
    invalid = np.zeros(n, bool)
    pulses = np.asarray(pulses, dtype=np.int64)
    ends = next_pulse_limits(pulses, n, fs, post_ms)
    hw = max(3, int(halfwidth_ms * fs / 1000))
    bl = int(blank_ms * fs / 1000)
    for t0, e in zip(pulses, ends):
        a = min(n, t0 + bl)
        v0 = baseline_fill_value(x, t0, fs)
        y[t0:a] = v0
        invalid[t0:a] = True
        seg = x[a:e]
        if len(seg) > 2 * hw + 2:
            fit = savgol_filter(seg, 2 * hw + 1, 3, mode="interp")
            y[a:e] = seg - fit + v0
    return CleanResult(y, invalid, {"method": "localpoly"})
