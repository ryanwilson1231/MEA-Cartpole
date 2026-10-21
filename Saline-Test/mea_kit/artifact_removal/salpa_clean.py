"""
SALPA artifact removal. Abbas, Oct 21 2026 (new).

What: SALPA (Wagenaar & Potter 2002) fits a cubic polynomial to a sliding window around each
sample and subtracts it. Slow artifact tails follow the fit and disappear; spikes (~1 ms) are too
fast for the fit and survive. Samples it cannot fix (saturated / during the pulse) come back as NaN,
which we mark invalid.
Why: Syrine's plan picks SALPA as the primary cleaner; Wagenaar's paper reports < 2 ms
undetectable period on 60-channel MCS data.

IMPORTANT (checked Oct 21 in the pip package, salpa 1.0): the `salpa.params()` / `salpa.run(in_file,
out_file, ...)` interface listed in Syrine's doc is NOT usable from pip (it lives in an un-exported
module and references a missing build/salpa binary). The working call is
    from salpa import salpa;  y = salpa(data_1d, tau, rail1, rail2, thresh, t_blankdepeg, t_ahead,
                                        t_chi2, tt_stimuli, t_forcepeg)
which works in memory - no raw-file export needed.
All salpa time arguments are in SAMPLES. Its defaults were tuned at 25 kHz, so we scale them to fs.
"""
import numpy as np

from .base import CleanResult
from ..common.signal import hf_sigma

DEFAULTS = {"halfwidth_ms": 2.0, "thr_rms": 3.0, "forcepeg_ms": 1.0, "rails": "auto"}


def check_available():
    from salpa import salpa  # noqa: F401
    return True


def estimate_rails(x, min_count=3):
    """Amplifier rails: the extreme value if the trace sits on it repeatedly (clipping plateau)."""
    mx, mn = float(np.max(x)), float(np.min(x))
    hi = mx - 1e-6 * abs(mx) if np.sum(x >= mx) >= min_count else np.inf
    lo = mn + 1e-6 * abs(mn) if np.sum(x <= mn) >= min_count else -np.inf
    return lo, hi


def clean_channel(x, fs, pulses, groups=None, halfwidth_ms=2.0, thr_rms=3.0, forcepeg_ms=1.0,
                  rails="auto", noise_mask=None, **_):
    from salpa import salpa
    x = np.asarray(x, dtype=np.float64)
    n = len(x)
    k = fs / 25000.0
    tau = max(3, int(round(halfwidth_ms * fs / 1000)))
    quiet = x if noise_mask is None else x[noise_mask]
    sigma = hf_sigma(quiet) if len(quiet) > 100 else hf_sigma(x)
    lo, hi = estimate_rails(x) if rails == "auto" else (-np.inf, np.inf)
    tt = [int(p) for p in pulses if 0 <= p < n - 1]
    y = salpa(x.astype(np.float32), tau, rail1=lo, rail2=hi, thresh=float(thr_rms * sigma),
              t_blankdepeg=max(1, int(5 * k)), t_ahead=max(1, int(5 * k)), t_chi2=max(5, int(15 * k)),
              tt_stimuli=tt if tt else None, t_forcepeg=max(1, int(forcepeg_ms * fs / 1000)))
    y = np.asarray(y, dtype=np.float64)
    invalid = ~np.isfinite(y)
    y[invalid] = 0.0  # salpa output is already baseline-free, so 0 is the right fill
    return CleanResult(y, invalid, {"method": "salpa", "tau_samples": tau, "sigma": float(sigma),
                                    "rails": (lo, hi), "invalid_frac": float(invalid.mean())})
