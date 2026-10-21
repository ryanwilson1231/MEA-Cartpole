"""Abbas, Oct 21 2026: every remover keeps the interface and actually removes a known artifact."""
import numpy as np
import pytest

from mea_kit.artifact_removal import available_removers, get_remover
from mea_kit.common.signal import bandpass

FS = 50_000


def make_trace(seed=0, n_pulses=30):
    rng = np.random.default_rng(seed)
    n = FS * 8
    x = rng.normal(0, 10, n) + 500.0
    pulses = np.arange(FS // 2, n - FS // 4, FS // 4)[:n_pulses]
    t = np.arange(int(0.04 * FS)) / FS * 1000
    art = 3000 * np.exp(-t / 0.6) + 200 * np.exp(-t / 5)
    for p in pulses:
        x[p: p + len(art)] += art
    return x, pulses


@pytest.mark.parametrize("name", ["none", "salpa", "blank", "template", "spikeinterface", "localpoly"])
def test_interface(name):
    if available_removers()[name] is not True:
        pytest.skip(f"{name} not installed")
    x, pulses = make_trace()
    r = get_remover(name).clean_channel(x, FS, pulses)
    assert r.x.shape == x.shape and np.all(np.isfinite(r.x))
    if r.invalid is not None:
        assert r.invalid.shape == x.shape


@pytest.mark.parametrize("name", ["salpa", "blank", "template", "spikeinterface", "localpoly"])
def test_artifact_reduced(name):
    """1-6 ms after each pulse (where the fast artifact still shows after the 300-3000 Hz band-pass),
    the cleaned trace must be at least 3x smaller than the raw one on the samples the remover kept."""
    if available_removers()[name] is not True:
        pytest.skip(f"{name} not installed")
    x, pulses = make_trace()
    raw = bandpass(x, FS)
    r = get_remover(name).clean_channel(x, FS, pulses)
    cl = bandpass(r.x, FS)
    valid = np.ones(len(x), bool) if r.invalid is None else ~r.invalid
    a, b = int(0.001 * FS), int(0.006 * FS)
    e_raw = np.mean([np.abs(raw[p + a: p + b]).max() for p in pulses])
    e_cl = np.mean([np.abs(cl[p + a: p + b][valid[p + a: p + b]]).max() if valid[p + a: p + b].any() else 0.0 for p in pulses])
    assert e_cl < e_raw / 3, (e_raw, e_cl)


def test_blank_marks_window():
    x, pulses = make_trace()
    r = get_remover("blank").clean_channel(x, FS, pulses, blank_ms=3.0, pre_ms=0.0)
    assert r.invalid[pulses[0]: pulses[0] + int(0.003 * FS)].all()
    assert not r.invalid[pulses[0] + int(0.004 * FS)]
