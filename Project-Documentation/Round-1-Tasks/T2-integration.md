# Role 2: Integration

| Owner | Hours | Test days | Works in |
|---|---|---|---|
| Ryan (co-lead) | 9–10 | Drives the computer for the whole checklist | `run_hardware.py`, new `config.py`, new `SETUP-WINDOWS.md` (all in `Baseline-Protocol/Hardware/`) |

**What this role is about:** owning the main program and the computer it runs on. Everyone codes against the function names you publish,
your settings file controls every run, and on test days you're at the keyboard.

| Due | What |
|---|---|
| Tue Oct 13 | Shared function names published (below) |
| Wed Oct 14 | Fix 4 (computer setup) |
| Fri Oct 16 | Fixes 1, 2 and 3 (first two modes); pull request open |
| Sat Oct 17 | Merge everyone's work; dry run on the fake device |
| Fri Oct 23 | Fix 3 (remaining modes); test-day fixes |
| Sat Oct 24 | Dry run on the recorded data |

**Shared function names (due Tue Oct 13, about 1 h).** In the files from Kai's split, add stub functions with docstrings so everyone codes
against the same names. Agree each with its owner:
- `recording.py` (role 3): `get_window(start_sample, n_samples)`, `pulse_samples(since_sample)`, `uv_per_count`, `samples_received`
- `stimulation.py` (role 4): `stimulate_predictable` / `stimulate_unpredictable` return the pulse schedule
- `spike_detection.py` (role 5): `calibrate_noise(...)`, `count_spikes(window_uv, fs, noise_sd, pulse_samples, mask_ms, margin_ms)`
- `session_logger.py` (role 7): `start_session(metadata)`, `log_step(...)`, `log_pulses(...)`, `close()`
- `fake_mea_device.py` (role 6): the same public methods as `MEADevice`
- `layouts.py` (Kai): `encode(observation, now_us)` returns the stimulation plan; `decode(counts_per_electrode)` returns the action

---

## Fix 1: A crash during setup leaves the MEA locked (P3) · due Fri Oct 16 · about 1 h

**The bug.** In `run_hardware.py`, `connect()` runs before the `try` block, so the cleanup in `finally` only covers errors that happen after
setup is completely finished:
```python
mea = MEADevice()
mea.connect()          # if this raises, close() never runs
...
try:
    for episode in range(EPISODES): ...
finally:
    mea.close()
```
And `close()` disconnects without ever telling the stimulator to stop:
```python
def close(self):
    if self.dacq is not None:
        self.dacq.StopDacq(0)
        self.dacq.Disconnect()
    if self.stg is not None:
        self.stg.Disconnect()
```
Setup is exactly where errors will happen on test day (role 3 is fixing a guaranteed one). Each crash leaves the device held by a dead
process, and the next run can't connect until someone power-cycles the interface board.

**Suggested solution.**
```python
mea = MEADevice()
try:
    mea.connect()
    ...                                   # the session
finally:
    mea.close()

def close(self):
    if self.stg is not None:
        try:
            self.stg.SendStop(1)          # stop trigger 1 (the one SendStart(1) uses)
        finally:
            self.stg.Disconnect()
    if self.dacq is not None:
        self.dacq.StopDacq(0)
        self.dacq.Disconnect()
```

**How to test it works.**
- **Laptop:** with a fake device whose `connect()` raises halfway through (after setting `dacq` but before `stg`), check that `close()` is
  still called and doesn't crash on the half-connected device.
- **Test day (check 5):** set `HEADSTAGE` to a wrong value on purpose so setup fails, then run twice in a row. The second run must get as far
  as the first, without power-cycling anything.

---

## Fix 2: Settings are scattered and never recorded · due Fri Oct 16 · about 1 h 15 min

**The bug.** Settings live in three files and nothing saves which values a run used:
- `mea_device.py`: `HEADSTAGE`, `SAMPLE_RATE`, `DATA_CHUNK_MS`, `STIM_AMPLITUDE_UV`, `PHASE_US`, `PULSES_PER_WINDOW`, `SPIKE_THRESHOLD_SD`
- `feedback.py`: `BALANCE_LIMIT_RAD`, `LEFT_CHANNELS`, `RIGHT_CHANNELS`
- `run_hardware.py`: `EPISODES`, `WINDOW_MS`, `RENDER`

Two runs a week apart can't be compared if nobody knows what changed in between. Test day needs `HEADSTAGE` changed in one obvious place.

**Suggested solution.** One `config.py` with a dataclass that every module reads from, saved in full into each session's log (role 7):
```python
@dataclass
class Config:
    headstage: int = 0                  # SCU input minus one (HS1 = 0 ... HS4 = 3); Kai posts the real value
    sample_rate: int = 50_000
    chunk_ms: int = 20
    stim_amplitude_uv: int = 75_000
    phase_us: int = 200
    pulses_per_window: int = 2
    window_ms: int = 100
    balance_limit_rad: float = 0.15
    mode: str = "closed_loop"
    duration_min: float = 5.0
    use_fake_device: bool = False
    timing_stream_index: int | None = None   # found on test day (role 3)
    layout: str = "baseline"                 # "rows" = layout v2 (Kai, role 1); baseline stays the default in round 1
    # For later rounds; leave at defaults in round 1:
    decoder_mapping: str = "normal"          # "swapped" flips which half means left
    physics: dict = field(default_factory=dict)   # e.g. {"length": 0.75}; applied to env.unwrapped
    normalize_halves: bool = False           # role 5's optional left/right balancing
```
If you apply physics overrides, set them on `env.unwrapped`. After changing `length` or `masspole`, also recompute `polemass_length` and
`total_mass`, because CartPole caches them.

**How to test it works.**
- **Laptop:** change `balance_limit_rad` in the config and confirm the fake-device run switches between predictable and unpredictable
  stimulation at the new angle.
- **Laptop:** confirm `session.json` contains every field.
- **Laptop:** set `decoder_mapping="swapped"` and confirm actions flip.

---

## Fix 3: There's only one way to run, and it counts episodes (P18) · first two modes due Fri Oct 16, the rest Fri Oct 23 · about 2 h 30 min

**The bug.** `run_hardware.py` always plays 20 episodes of the game (about 1–2 minutes) and stops. Later experiments need things it can't
do:
- recording activity with *no* stimulation (to see a culture's baseline);
- checking whether stimulation evokes responses;
- running for a fixed amount of time.

Both published studies we build on ran structured sessions like this (see `Experiment-Design-Notes.md`).

**Suggested solution.** A `mode` setting:

| Mode | Due | Does |
|---|---|---|
| `spontaneous` | Fri Oct 16 | Record for `duration_min` with no stimulation; save each electrode's spike rate and each half's rate |
| `closed_loop` | Fri Oct 16 | The current game, stopping after `duration_min` instead of a set number of episodes |
| `stim_check` | Fri Oct 23 | 50 left-only pulses, then 50 right-only, at 1 Hz; save each electrode's spike count 0–10 ms and 10–200 ms after each pulse (with role 5's artifact window) |
| `session` | Fri Oct 23 | `spontaneous` → `stim_check` → `closed_loop` → `spontaneous` |

**How to test it works.**
- **Laptop (fake device):** every mode runs and stops within 1 s of its set duration.
- **Laptop (fake device):** `stim_check` with the fake device's "evoked spikes" option shows more responses on the stimulated side.
- **Test day 1 (check 6):** `spontaneous` 2 min, then `closed_loop` 5 min.
- **Test day 2:** the full `session` mode.

---

## Fix 4: Nobody has written down how to set up the computer (P22) · due Wed Oct 14 · about 1 h 30 min

**The bug.** Nothing tells you what the Windows computer needs, and the library is picky. `McsUsbNet.dll` is 64-bit, built for .NET
Framework 4, and contains native Windows code linked against the Microsoft Visual C++ runtime. The MEA's USB driver comes from MCS's own
software. A missing piece shows up as a confusing error on test day.

**Suggested solution.** Install, then write `Baseline-Protocol/Hardware/SETUP-WINDOWS.md` with the exact versions:
- Windows on an Intel/AMD processor (not ARM). The manual lists Windows 10; if you're on Windows 11, check MCS's site.
- Multi Channel Suite from multichannelsystems.com (installs the USB driver), plus MCS Filter Configuration (`McsFilterConfig.exe`,
  a separate small installer; test day uses it to read the hardware filter settings, manual p. 15).
- 64-bit Python and `pythonnet` 3.
- Microsoft Visual C++ 2015–2022 x64 runtime (usually already installed).
- Plug the interface board's USB-C cable straight into the laptop: no hub, no dock.
- Close Multi Channel Experimenter before running Python. Only one program can drive the device at a time.

Send the Python and package versions to role 6 for `requirements.txt`.

**How to test it works.** From the repo root on your computer:
```python
import clr
from pathlib import Path
clr.AddReference(str(Path("Baseline-Protocol/Hardware/McsUsbNet.dll").resolve()))
from Mcs.Usb import CMcsUsbListNet, DeviceEnumNet
print("DLL loaded. MCS devices found:", CMcsUsbListNet(DeviceEnumNet.MCS_DEVICE_USB).Count)
```
It prints 0 devices with nothing plugged in, and 1 on test day with the hardware connected.

---

## Integration work

| When | What | About |
|---|---|---|
| Sat Oct 17 | Merge everyone's pull requests; run the full loop on the fake device; tell Kai what's not ready | 1 h |
| Sun Oct 18 | Drive the computer for the whole checklist | test day |
| Fri Oct 23 | Fix the integration problems on your test-day fix list | 1 h |
| Sat Oct 24 | Merge; dry run using role 6's replay mode on the recorded data | 30 min |
| Sun Oct 25 | Drive test day 2 | test day |

## Done when
- The shared function names are published.
- The setup doc and smoke test work on your computer.
- Every mode runs on the fake device and on the hardware.
- Checks 5 and 6 pass on test day 2.
