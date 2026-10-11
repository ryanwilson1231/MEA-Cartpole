"""
Offline checks of the Baseline-Protocol hardware code. No MEA, no Windows, no DLL needed.

What it checks:
  1. The spike detector (count_spikes) on pure noise and on planted spikes,
     and where its false spikes come from.
  2. The pulse trains mea_device.py sends to the stimulator (durations, 20 us resolution).
  3. What CartPole scores mean: stuck, random, and "reflex" policies, so a session's
     episode lengths can be read correctly.

Run from the repo root:
    pip install numpy scipy gymnasium
    python Project-Documentation/Evidence/offline_checks.py
"""
import sys
import types
from pathlib import Path
from unittest import mock

import numpy as np
import gymnasium as gym

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "Baseline-Protocol" / "Hardware"))

# Stand-ins for pythonnet and the MCS DLL so mea_device.py can be imported off the lab PC.
clr = types.ModuleType("clr")
clr.AddReference = lambda *a, **k: None
system = types.ModuleType("System")
for name in ["Int32", "UInt32", "UInt64", "Array", "IntPtr"]:
    setattr(system, name, mock.MagicMock())
interop = types.ModuleType("System.Runtime.InteropServices")
interop.Marshal = mock.MagicMock()
mcs = types.ModuleType("Mcs.Usb")
for name in ["CMcsUsbListNet", "DeviceEnumNet", "CMeaUSBDeviceNet", "CStg200xDownloadNet", "CSCUFunctionNet",
             "DataModeEnumNet", "DigitalDatastreamEnableEnumNet", "ChannelBlockTypeNet", "SampleSizeNet",
             "SampleDstSizeNet", "ElectrodeModeEnumNet", "ElectrodeDacMuxEnumNet", "STG_DestinationEnumNet"]:
    setattr(mcs, name, mock.MagicMock())
sys.modules.update({"clr": clr, "System": system, "System.Runtime": types.ModuleType("System.Runtime"),
                    "System.Runtime.InteropServices": interop, "Mcs": types.ModuleType("Mcs"), "Mcs.Usb": mcs})

import mea_device as md  # noqa: E402
from feedback import BALANCE_LIMIT_RAD  # noqa: E402

rng = np.random.default_rng(0)
FS = md.SAMPLE_RATE
N = FS * 100 // 1000  # one 100 ms listening window


def section(title):
    print(f"\n=== {title} ===")


section("1a. Spike detector on pure noise (no spikes at all)")
windows, false_total, positions = 50, 0, []
for _ in range(windows):
    noise = rng.normal(0, 10, (60, N))
    false_total += md.count_spikes(noise).sum()
    from scipy.signal import butter, sosfiltfilt
    sos = butter(2, [300, 3000], btype="bandpass", fs=FS, output="sos")
    f = sosfiltfilt(sos, noise, axis=1)
    sd = np.median(np.abs(f), axis=1) / 0.6745
    below = f < -md.SPIKE_THRESHOLD_SD * sd[:, None]
    _, t = np.nonzero(below[:, 1:] & ~below[:, :-1])
    positions += list(t)
positions = np.array(positions)
per_ch = false_total / (windows * 60)
print(f"false spikes per electrode per 100 ms window: {per_ch:.3f}  (~{per_ch * 10:.1f} fake spikes/s per electrode)")
print(f"share of false spikes within 2 ms of a window edge: {np.mean((positions < 100) | (positions > N - 100)):.0%}")
print("for comparison, a culture firing at 1-5 Hz gives 0.1-0.5 real spikes per electrode per window")

section("1b. Spike detector on planted spikes")
x = rng.normal(0, 10, (60, N))
planted = np.zeros(60, int)
for ch in range(60):
    k = rng.integers(0, 6)
    for t0 in rng.choice(np.arange(200, N - 200), size=k, replace=False):
        x[ch, t0:t0 + 15] += -80 * np.hanning(15)  # 0.3 ms, -80 uV spike, 8x the noise SD
    planted[ch] = k
found = md.count_spikes(x)
print(f"planted {planted.sum()}, detected {found.sum()}, electrodes counted exactly right: {(found == planted).sum()}/60")

section("2. Pulse trains sent to the stimulator")
dev = md.MEADevice.__new__(md.MEADevice)
amps, durs, _ = dev._pulse_train([0, 50_000], 100)
print(f"predictable side: amplitudes (uV) {amps}")
print(f"                  durations (us)  {durs}  total {sum(durs)} us")
print(f"silent side:      {dev._pulse_train([], 100)[:2]}")
bad = 0
for _ in range(2000):
    pulse_us = 2 * md.PHASE_US
    n_slots = 100 * 1000 // pulse_us
    onsets = sorted(int(s) * pulse_us for s in rng.choice(n_slots, md.PULSES_PER_WINDOW, replace=False))
    _, d, _ = dev._pulse_train(onsets, 100)
    if sum(d) != 100_000 or any(v <= 0 for v in d) or any(v % 20 for v in d):
        bad += 1
print(f"unpredictable: {bad}/2000 random trains had a wrong total, an empty segment, or a duration that isn't a")
print("multiple of the stimulator's 20 us time resolution (manual, Technical Specifications)")

section("3. What CartPole episode lengths mean (400 episodes per policy)")
env = gym.make("CartPole-v1")


def run(policy, episodes=400):
    lengths, unbalanced, total = [], 0, 0
    for ep in range(episodes):
        obs, _ = env.reset(seed=10_000 + ep)
        done, steps = False, 0
        while not done:
            unbalanced += abs(obs[2]) >= BALANCE_LIMIT_RAD
            obs, _, term, trunc, _ = env.step(policy(obs))
            done, steps, total = term or trunc, steps + 1, total + 1
        lengths.append(steps)
    return np.mean(lengths), np.std(lengths), unbalanced / total


def reflex(p_correct):
    def policy(obs):
        correct = 1 if obs[2] > 0 else 0  # push toward the side the pole leans
        return correct if rng.random() < p_correct else 1 - correct
    return policy


for label, policy in [("always pushes one way", lambda o: 1),
                      ("coin flip", lambda o: int(rng.integers(2))),
                      ("pushes toward lean 60% of steps", reflex(0.6)),
                      ("pushes toward lean 75% of steps", reflex(0.75)),
                      ("pushes toward lean every step", reflex(1.0))]:
    mean, sd, frac = run(policy)
    print(f"{label:<34} {mean:5.1f} +/- {sd:4.1f} steps   (steps past the balance limit: {frac:.0%})")
