"""Abbas, Oct 21 2026: hardware blanking must be ON in every default block (amplifier protection)."""
from mea_kit.hardware import saline_protocol
from mea_kit.hardware import device_fake


def _run(tmp_path, extra):
    calls = []
    orig = device_fake.FakeDevice.set_blanking

    def spy(self, on):
        calls.append(bool(on))
        return orig(self, on)

    device_fake.FakeDevice.set_blanking = spy
    try:
        saline_protocol.main(["--dry-run", "--out", str(tmp_path), "--game-windows", "3", "--baseline-s", "1",
                              "--sweep-pulses", "1", "--sweep-electrodes", "0-1"] + extra)
    finally:
        device_fake.FakeDevice.set_blanking = orig
    return calls


def test_default_plan_never_turns_blanking_off(tmp_path):
    calls = _run(tmp_path, [])
    assert calls and all(calls)


def test_r4_listed_without_flag_is_skipped(tmp_path):
    calls = _run(tmp_path, ["--blocks", "baseline,R4_blanking_off,R2_current"])
    assert all(calls)


def test_r4_with_flag_turns_blanking_back_on_after(tmp_path):
    calls = _run(tmp_path, ["--blocks", "R4_blanking_off,R2_current", "--include-blanking-off"])
    assert False in calls and calls[-1] is True
