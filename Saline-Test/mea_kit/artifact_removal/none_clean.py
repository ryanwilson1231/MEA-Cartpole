"""Reference: no cleaning. Abbas, Oct 21 2026 (new)."""
import numpy as np
from .base import CleanResult

DEFAULTS = {}


def check_available():
    return True


def clean_channel(x, fs, pulses, groups=None, **params):
    return CleanResult(np.asarray(x, dtype=np.float64).copy(), None, {"method": "none"})
