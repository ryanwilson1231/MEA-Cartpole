"""
Shared helpers for the three reward signaling methods, using the team's v2
encoding / decoding layout (Kai's walkthrough).

Chip layout (MCS 60 electrode MEA, labels are column digit then row digit):

  INPUT   bottom row   28 38 48 | 58 68 78    left three = left tilt, right three = right tilt
  OUTPUT  top row      21 31 41 | 51 61 71    left three = push left, right three = push right
  FEEDBACK (our choice, row 5)  25 35 45 55 65 75    reward / penalty stimulation only
  everything else: recording only (whole-dish firing rate / drift). 15 is the reference.

Encoding: pole angle picks ONE input electrode (bins 0-2, 2-6, 6-12 degrees per side,
0.5 degree hysteresis at the 2 and 6 degree edges, 0 counts as left). Angular velocity sets
the pulse rate (25 Hz still, faster when falling away from vertical, slower when
recovering, capped 10 to 40 Hz). The pulse train runs continuously across game steps.
Amplitude is fixed (not information carrying).

Decoding: each output electrode's spike count is divided by its own baseline count, then the
mean of the left three is compared with the mean of the right three. Ties are random.

Timing: each game step is one 200 ms cycle (the game waits for the culture).

Simulation notes: the baseline gives one neuron per electrode, and the electrode to channel
index map is just sorted label order, so the layout is a label only, with no physical
distance in the simulation. Nothing here is tuned. Treat results as a smoke test.
"""
import os
import sys

import numpy as np
import gymnasium as gym

_HERE = os.path.dirname(os.path.abspath(__file__))
# Find the team's baseline files (simulated_mea.py).
for _rel in ("baseline", "Baseline-Protocol/Brian2", "../Baseline-Protocol/Brian2",
             "../../Baseline-Protocol/Brian2", "."):
    _p = os.path.normpath(os.path.join(_HERE, _rel))
    if os.path.exists(os.path.join(_p, "simulated_mea.py")):
        sys.path.insert(0, _p)
        break
from brian2 import ms  # noqa: E402
from simulated_mea import SimulatedMEA  # noqa: E402  (baseline, unchanged)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from realistic_mea import RealisticMEA  # noqa: E402

# Which simulated dish to use. "realistic" (default) or "baseline" (60 neurons, one per electrode).
# Choose with:  REWARD_SIM=baseline python method1_rest_and_burst.py ...
SIM = os.environ.get("REWARD_SIM", "realistic")

# ---- electrode labels -> simulation channel index (sorted label order) ----------------
_CORNERS = {11, 18, 81, 88}
LABELS = sorted(c * 10 + r for c in range(1, 9) for r in range(1, 9)
                if c * 10 + r not in _CORNERS)          # 60 electrodes
CH = {label: i for i, label in enumerate(LABELS)}

BIN_ORDER = "A"   # "A": small-angle bins in the centre, "B": small-angle bins at the edges
INPUT_LEFT_LABELS = [28, 38, 48]
INPUT_RIGHT_LABELS = [58, 68, 78]
OUTPUT_LEFT_LABELS = [21, 31, 41]
OUTPUT_RIGHT_LABELS = [51, 61, 71]
FEEDBACK_LABELS = [25, 35, 45, 55, 65, 75]    # our proposal, not yet agreed with the team

# per side, electrode for angle bin 0 (0-2 deg), 1 (2-6), 2 (6-12)
if BIN_ORDER == "A":
    LEFT_BIN_LABEL = {0: 48, 1: 38, 2: 28}
    RIGHT_BIN_LABEL = {0: 58, 1: 68, 2: 78}
else:
    LEFT_BIN_LABEL = {0: 28, 1: 38, 2: 48}
    RIGHT_BIN_LABEL = {0: 78, 1: 68, 2: 58}

SENSORY_LEFT = [CH[l] for l in INPUT_LEFT_LABELS]
SENSORY_RIGHT = [CH[l] for l in INPUT_RIGHT_LABELS]
MOTOR_LEFT = [CH[l] for l in OUTPUT_LEFT_LABELS]
MOTOR_RIGHT = [CH[l] for l in OUTPUT_RIGHT_LABELS]
FEEDBACK = [CH[l] for l in FEEDBACK_LABELS]

WINDOW_MS = 200          # one game step = one 200 ms cycle
ENCODE_CURRENT = 30.0    # fixed input amplitude: fired a lone neuron 29 of 30 times in a quick check
PULSE_CURRENT = 30.0     # feedback pulses use the same amplitude
PULSE_WIDTH_MS = 1.0     # simulation pulse width (the chip uses 200 microseconds per phase)
BASE_RATE_HZ = 25.0
RATE_MIN_HZ, RATE_MAX_HZ = 10.0, 40.0
RATE_PER_RAD_S = 15.0    # Hz per rad/s of angular velocity. MY ASSUMPTION, not in the walkthrough.
BIN_EDGES_DEG = (2.0, 6.0)
HYSTERESIS_DEG = 0.5
BASELINE_WINDOWS = 10    # windows of spontaneous activity used to normalize each output electrode


class Culture:
    """The baseline simulated dish plus pulse level control."""

    def __init__(self, seed):
        np.random.seed(seed)
        from brian2 import seed as brian_seed
        brian_seed(seed)
        if SIM == "baseline":
            self.mea = SimulatedMEA()
            self.n = self.mea.neurons
        else:
            self.mea = RealisticMEA(LABELS)
            self.n = self.mea.neurons
        # spontaneous rate of each output electrode, used to normalize the decode
        counts = np.zeros(60)
        for _ in range(BASELINE_WINDOWS):
            counts += self.run(WINDOW_MS)
        self.baseline = np.maximum(counts / BASELINE_WINDOWS, 0.5)

    def _set(self, current):
        if SIM == "baseline":
            self.n.I = current
        else:
            self.mea.set_current(current)

    def _counts(self):
        if SIM == "baseline":
            return np.array(self.mea.spikes.count)
        return self.mea.channel_counts()

    def run(self, window_ms, constant=None, pulses=()):
        """
        Run the network for window_ms and return spikes per channel (length 60).
        constant: dict {tuple_of_channels: current} held for the whole window.
        pulses:   list of (channels, onset_ms, current) brief pulses of PULSE_WIDTH_MS.
        """
        before = self._counts()
        base = np.zeros(60)
        for channels, current in (constant or {}).items():
            base[list(channels)] = current

        # cut the window at every pulse edge
        edges = {0.0, float(window_ms)}
        for _, onset, _ in pulses:
            edges.add(float(onset))
            edges.add(min(float(onset) + PULSE_WIDTH_MS, float(window_ms)))
        edges = sorted(e for e in edges if 0.0 <= e <= window_ms)
        for start, stop in zip(edges[:-1], edges[1:]):
            current = base.copy()
            for channels, onset, amp in pulses:
                if onset <= start < onset + PULSE_WIDTH_MS:
                    current[list(channels)] += amp
            self._set(current)
            self.mea.network.run((stop - start) * ms)
        self._set(np.zeros(60))
        return self._counts() - before

    def idle(self, duration_ms, pulses=()):
        """Let time pass with no sensory input (used for stimulation between episodes)."""
        self.run(duration_ms, pulses=pulses)


class Encoder:
    """Angle picks one input electrode; angular velocity sets a continuous pulse rate."""

    def __init__(self):
        self.side = None
        self.bin = None
        self.next_ms = 0.0     # time until the next pulse, carried across steps

    def _bin(self, angle):
        deg = abs(np.degrees(angle))
        side = "L" if angle <= 0 else "R"          # 0 counts as left
        raw = int(deg >= BIN_EDGES_DEG[0]) + int(deg >= BIN_EDGES_DEG[1])
        if side == self.side and self.bin is not None and raw != self.bin:
            lo = (0.0, BIN_EDGES_DEG[0], BIN_EDGES_DEG[1])[self.bin] - HYSTERESIS_DEG
            hi = (BIN_EDGES_DEG[0], BIN_EDGES_DEG[1], 1e9)[self.bin] + HYSTERESIS_DEG
            if lo <= deg < hi:
                raw = self.bin                      # stay put inside the hysteresis band
        self.side, self.bin = side, raw
        return side, raw

    def pulses(self, angle, ang_vel):
        side, b = self._bin(angle)
        label = (LEFT_BIN_LABEL if side == "L" else RIGHT_BIN_LABEL)[b]
        away = np.sign(angle) * ang_vel            # positive = falling away from vertical
        rate = float(np.clip(BASE_RATE_HZ + RATE_PER_RAD_S * away, RATE_MIN_HZ, RATE_MAX_HZ))
        gap = 1000.0 / rate
        out, t = [], self.next_ms
        while t < WINDOW_MS:
            out.append(((CH[label],), t, ENCODE_CURRENT))
            t += gap
        self.next_ms = t - WINDOW_MS
        return out


def decode(counts, baseline, rng, tally=None):
    """Baseline-normalized mean of the left three vs the right three output electrodes."""
    left = (counts[MOTOR_LEFT] / baseline[MOTOR_LEFT]).mean()
    right = (counts[MOTOR_RIGHT] / baseline[MOTOR_RIGHT]).mean()
    if left > right:
        return 0
    if right > left:
        if tally is not None:
            tally["right"] += 1
        return 1
    if tally is not None:
        tally["ties"] += 1
    return int(rng.integers(2))


def burst(channels, start_ms=0.0, n_pulses=5, rate_hz=100):
    """A short burst: n_pulses at rate_hz (default 5 pulses at 100 per second)."""
    gap = 1000.0 / rate_hz
    return [(tuple(channels), start_ms + i * gap, PULSE_CURRENT) for i in range(n_pulses)]


class FeedbackPolicy:
    """Subclass this. Return pulses to add to each window, and act at episode end."""
    name = "null"

    def step_pulses(self, prev_angle, angle, step):
        return []

    def end_episode(self, culture, length):
        pass


def play(policy, seed, episodes, log=None):
    """Play CartPole with the culture. Returns the list of episode lengths."""
    culture = Culture(seed)
    rng = np.random.default_rng(seed)
    env = gym.make("CartPole-v1")
    lengths = []
    for ep in range(episodes):
        obs, _ = env.reset(seed=seed * 1000 + ep)
        encoder = Encoder()
        steps, done = 0, False
        prev_angle = obs[2]
        while not done:
            angle, ang_vel = obs[2], obs[3]
            pulses = encoder.pulses(angle, ang_vel) + policy.step_pulses(prev_angle, angle, steps)
            counts = culture.run(WINDOW_MS, pulses=pulses)
            action = decode(counts, culture.baseline, rng)
            prev_angle = angle
            obs, _, term, trunc, _ = env.step(action)
            done = term or trunc
            steps += 1
        lengths.append(steps)
        policy.end_episode(culture, steps)
        if log:
            log(ep, steps)
    env.close()
    return lengths


def summarize(results, first=15, last=15):
    """results: {condition: [list of lengths per seed]}. Prints first vs last mean."""
    print(f"{'condition':<22}{'first ' + str(first):>10}{'last ' + str(last):>10}{'change':>9}   per seed (last)")
    for cond, runs in results.items():
        f = [np.mean(r[:first]) for r in runs]
        l = [np.mean(r[-last:]) for r in runs]
        print(f"{cond:<22}{np.mean(f):>10.1f}{np.mean(l):>10.1f}{np.mean(l) - np.mean(f):>+9.1f}   "
              + ", ".join(f"{x:.1f}" for x in l))


# ---------------------------------------------------------------- running and caching
RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results" if SIM == "realistic" else "results_baseline")


def run_or_load(name, make_policy, seed, episodes):
    """Run one condition for one seed, saving to results/ so reruns resume."""
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, f"{name}_s{seed}_e{episodes}.csv")
    if os.path.exists(path):
        return [int(x) for x in np.loadtxt(path, skiprows=1, ndmin=1)]
    lengths = play(make_policy(seed), seed, episodes)
    np.savetxt(path, lengths, fmt="%d", header="steps", comments="")
    return lengths


def run_experiment(conditions, seeds, episodes, first=15, last=15):
    """conditions: {name: make_policy(seed)}. Runs each over seeds and prints a summary."""
    results = {}
    for name, make_policy in conditions.items():
        results[name] = []
        for seed in range(seeds):
            results[name].append(run_or_load(name, make_policy, seed, episodes))
            print(f"done {name} seed {seed}: last {last} mean "
                  f"{np.mean(results[name][-1][-last:]):.1f}", flush=True)
    summarize(results, first, last)
    return results
