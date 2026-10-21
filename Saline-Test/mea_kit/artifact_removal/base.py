"""Shared result type + registry. Abbas, Oct 21 2026 (new)."""
from dataclasses import dataclass, field
import importlib

import numpy as np


@dataclass
class CleanResult:
    x: np.ndarray
    invalid: np.ndarray = None   # True where the cleaner blanked / has no data
    info: dict = field(default_factory=dict)


REMOVER_DESCRIPTIONS = {
    "none": "No cleaning (reference)",
    "salpa": "SALPA local-polynomial fit (salpa package)",
    "blank": "Simple blanking (replace window after pulse)",
    "template": "Template subtraction (median artifact over repeats)",
    "spikeinterface": "SpikeInterface remove_artifacts",
    "localpoly": "SALPA-like local cubic fit (pure Python fallback)",
}

_MODULES = {
    "none": "mea_kit.artifact_removal.none_clean",
    "salpa": "mea_kit.artifact_removal.salpa_clean",
    "blank": "mea_kit.artifact_removal.blank_clean",
    "template": "mea_kit.artifact_removal.template_clean",
    "spikeinterface": "mea_kit.artifact_removal.si_clean",
    "localpoly": "mea_kit.artifact_removal.localpoly_clean",
}


def get_remover(name):
    """Returns the module; call module.clean_channel(...). Raises ImportError if its package is missing."""
    mod = importlib.import_module(_MODULES[name])
    mod.check_available()
    return mod


def available_removers():
    out = {}
    for n in _MODULES:
        try:
            get_remover(n)
            out[n] = True
        except Exception as e:  # noqa: BLE001
            out[n] = f"unavailable: {e}"
    return out


def baseline_fill_value(x, t0, fs, pre_ms=2.0):
    a = max(0, t0 - int(pre_ms * fs / 1000))
    seg = x[a:t0]
    return float(np.median(seg)) if len(seg) else float(x[t0])


def next_pulse_limits(pulses, n, fs, post_ms):
    """For each pulse, the end of its post window: min(t0 + post_ms, next pulse)."""
    post = int(post_ms * fs / 1000)
    ends = np.minimum(pulses + post, np.r_[pulses[1:], n])
    return np.minimum(ends, n)
