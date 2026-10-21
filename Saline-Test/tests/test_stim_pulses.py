"""Abbas, Oct 21 2026: cathodic-first trains + safety limits."""
import pytest

from mea_kit.hardware.stim_pulses import UnsafeStimulus, check_safety, predictable_onsets, pulse_train


def test_cathodic_first_and_timing():
    amps, durs, active = pulse_train([0, 50_000], 100, 10_000, 200)
    assert amps[:2] == [-10_000, 10_000]          # negative phase first
    assert sum(durs) == 100_000                   # whole window in microseconds
    assert active[:2] == [1, 1] and active[2] == 0
    assert predictable_onsets(100, 2) == [0, 50_000]


def test_safety_limits():
    check_safety("current", 10_000, 200)          # 2 nC: fine
    with pytest.raises(UnsafeStimulus):
        check_safety("current", 50_000, 200)      # 50 uA
    with pytest.raises(UnsafeStimulus):
        check_safety("voltage", 500_000, 200)     # 500 mV
