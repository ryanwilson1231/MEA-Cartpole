"""
Cathodic-first biphasic pulse trains. Abbas, Oct 21 2026 (new).

Why: mea_device.py builds +amplitude then -amplitude (anodic-first). We agreed on cathodic-first
(negative phase first), so every train here is [-A, +A]. Format matches mea_device._pulse_train:
(amplitudes, durations_us, stim_active_flags) for one stimulus generator.
"""
from . import config as C


class UnsafeStimulus(ValueError):
    pass


def check_safety(mode, amplitude, phase_us, allow_high_charge=False):
    a = abs(amplitude)
    if mode == "current":
        q_nc = a * 1e-9 * phase_us * 1e-6 * 1e9
        if not allow_high_charge and (a > C.MAX_CURRENT_NA or q_nc > C.MAX_CHARGE_NC_PER_PHASE):
            raise UnsafeStimulus(f"{a/1000:.1f} uA x {phase_us} us = {q_nc:.2f} nC/phase exceeds limits "
                                 f"({C.MAX_CURRENT_NA/1000} uA, {C.MAX_CHARGE_NC_PER_PHASE} nC)")
        return q_nc
    if mode == "voltage":
        if not allow_high_charge and a > C.MAX_VOLTAGE_UV:
            raise UnsafeStimulus(f"{a/1000:.0f} mV exceeds MAX_VOLTAGE_UV")
        return None
    raise ValueError(mode)


def pulse_train(onsets_us, window_ms, amplitude, phase_us, polarity="cathodic_first"):
    """One generator's waveform over window_ms with biphasic pulses at onsets_us."""
    first, second = (-abs(amplitude), abs(amplitude)) if polarity == "cathodic_first" else (abs(amplitude), -abs(amplitude))
    amps, durs, active = [], [], []
    t = 0
    for on in sorted(onsets_us):
        if on < t:
            raise ValueError("pulses overlap")
        if on > t:
            amps.append(0); durs.append(int(on - t)); active.append(0)
        amps += [first, second]
        durs += [int(phase_us), int(phase_us)]
        active += [1, 1]
        t = on + 2 * phase_us
    end = int(window_ms * 1000)
    if end > t:
        amps.append(0); durs.append(end - t); active.append(0)
    return amps, durs, active


def silent(window_ms):
    return pulse_train([], window_ms, 0, 0)


def predictable_onsets(window_ms=C.WINDOW_MS, n=C.PULSES_PER_WINDOW):
    spacing = window_ms * 1000 // n
    return [i * spacing for i in range(n)]
