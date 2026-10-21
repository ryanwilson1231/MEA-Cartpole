"""
SpikeInterface remove_artifacts. Abbas, Oct 21 2026 (new).

What: spikeinterface.preprocessing.remove_artifacts(recording, list_triggers, ms_before, ms_after, mode)
  mode="zeros"  -> sets the window to 0 (same idea as our simple blanking)
  mode="linear" / "cubic" -> interpolates straight across the window (no step)
  mode="median" / "average" -> SpikeInterface's own template subtraction
Why: it is the standard community tool, one line to use, and it is what Syrine listed.
Default here is "cubic" so this column is not a duplicate of the blanking column.
We subtract the channel's median first so "zeros" means "baseline", not a DC step.
Checked against spikeinterface 0.105.3.
"""
import numpy as np

from .base import CleanResult

DEFAULTS = {"ms_before": 0.1, "ms_after": 3.0, "mode": "cubic"}


def check_available():
    import spikeinterface.preprocessing  # noqa: F401
    return True


def clean_channel(x, fs, pulses, groups=None, ms_before=0.1, ms_after=3.0, mode="cubic", **_):
    from spikeinterface.core import NumpyRecording
    import spikeinterface.preprocessing as spre
    x = np.asarray(x, dtype=np.float64)
    dc = float(np.median(x))
    n = len(x)
    trig = [int(p) for p in pulses if int(ms_before * fs / 1000) <= p < n - int(ms_after * fs / 1000) - 2]
    rec = NumpyRecording([(x - dc).astype(np.float32)[:, None]], sampling_frequency=float(fs))
    if trig:
        kw = {}
        if mode in ("median", "average"):
            kw["list_labels"] = [["a"] * len(trig)]
        rec = spre.remove_artifacts(rec, list_triggers=[trig], ms_before=ms_before, ms_after=ms_after, mode=mode, **kw)
    y = np.asarray(rec.get_traces(segment_index=0)[:, 0], dtype=np.float64) + dc
    invalid = np.zeros(n, bool)
    if mode in ("zeros", "linear", "cubic"):
        a, b = int(ms_before * fs / 1000), int(ms_after * fs / 1000)
        for p in trig:
            invalid[p - a: p + b] = True
    return CleanResult(y, invalid, {"method": "spikeinterface", "mode": mode, "ms_after": ms_after})
