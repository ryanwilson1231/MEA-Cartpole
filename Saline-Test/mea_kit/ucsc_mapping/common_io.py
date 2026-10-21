"""Small helpers shared by the mapping versions. Abbas, Oct 21 2026 (new)."""
import numpy as np


def pulses_by_electrode(block, kind="sweep"):
    out = {}
    for p in block.pulses:
        if (kind is None or p.get("kind") == kind) and p.get("electrodes"):
            out.setdefault(p["electrodes"][0], []).append(p["pulse_sample"])
    return {e: np.array(sorted(v)) for e, v in out.items()}


def all_pulse_samples(block):
    return np.array(sorted(p["pulse_sample"] for p in block.pulses))
