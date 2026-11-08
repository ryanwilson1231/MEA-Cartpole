"""
Shared helpers for the three reward signaling methods.

Uses the team's baseline SimulatedMEA unchanged (baseline/simulated_mea.py) and
rewires only how the game talks to it, so the lean side shortcut is gone:

  channels  0 to  7   SENSORY LEFT    stimulated when the pole leans left
  channels  8 to 15   SENSORY RIGHT   stimulated when the pole leans right
  channels 16 to 23   FEEDBACK        reward / penalty stimulation goes here only
  channels 24 to 41   MOTOR LEFT      spikes here vote for "push left"  (action 0)
  channels 42 to 59   MOTOR RIGHT     spikes here vote for "push right" (action 1)

Why: in the baseline, the side that gets stimulated is also the side the decoder
reads, so the stimulus hands over the answer. Here the sensory and motor channels
are different neurons, so the network has to learn which motor side should respond
to which sensory side. Feedback uses its own channels so it never carries state.

Nothing here is tuned. Treat results as a smoke test of each method, not evidence.
"""
import os
import sys

import numpy as np
import gymnasium as gym

_HERE = os.path.dirname(os.path.abspath(__file__))
# Find the team's baseline files (feedback.py, simulated_mea.py). Put this folder at the
# repo root (next to Baseline-Protocol/) or inside it; a local "baseline" folder also works.
for _rel in ("baseline", "Baseline-Protocol/Brian2", "../Baseline-Protocol/Brian2",
             "../../Baseline-Protocol/Brian2", "."):
    _p = os.path.normpath(os.path.join(_HERE, _rel))
    if os.path.exists(os.path.join(_p, "simulated_mea.py")):
        sys.path.insert(0, _p)
        break
from brian2 import ms  # noqa: E402
from simulated_mea import SimulatedMEA  # noqa: E402  (baseline, unchanged)

SENSORY_LEFT = list(range(0, 8))
SENSORY_RIGHT = list(range(8, 16))
FEEDBACK = list(range(16, 24))
MOTOR_LEFT = list(range(24, 42))
MOTOR_RIGHT = list(range(42, 60))

WINDOW_MS = 100          # one game step = one 100 ms stimulate and listen window
SENSORY_CURRENT = 10.0   # same scale as the baseline STIM_CURRENT
PULSE_CURRENT = 20.0     # brief, strong, like an electrode pulse
PULSE_WIDTH_MS = 1.0
FALL_ANGLE = 0.2095      # CartPole ends the episode here (12 degrees)


class Culture:
    """The baseline simulated dish plus pulse level control."""

    def __init__(self, seed):
        np.random.seed(seed)
        from brian2 import seed as brian_seed
        brian_seed(seed)
        self.mea = SimulatedMEA()
        self.n = self.mea.neurons

    def run(self, window_ms, constant=None, pulses=()):
        """
        Run the network for window_ms and return spikes per channel (length 60).
        constant: dict {tuple_of_channels: current} held for the whole window.
        pulses:   list of (channels, onset_ms, current) brief pulses of PULSE_WIDTH_MS.
        """
        before = np.array(self.mea.spikes.count)
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
            self.n.I = current
            self.mea.network.run((stop - start) * ms)
        self.n.I = 0
        return np.array(self.mea.spikes.count) - before

    def idle(self, duration_ms, pulses=()):
        """Let time pass with no sensory input (used for stimulation between episodes)."""
        self.run(duration_ms, pulses=pulses)


def sensory_input(angle):
    """State encoding: the lean side group gets a current that grows with the tilt."""
    strength = 0.5 + 0.5 * min(abs(angle) / FALL_ANGLE, 1.0)
    group = SENSORY_LEFT if angle < 0 else SENSORY_RIGHT
    return {tuple(group): SENSORY_CURRENT * strength}


def decode(counts, rng):
    """More motor spikes on the left -> 0, right -> 1, tie -> random."""
    left = counts[MOTOR_LEFT].sum()
    right = counts[MOTOR_RIGHT].sum()
    if left > right:
        return 0
    if right > left:
        return 1
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
        angle, prev_angle, steps, done = obs[2], obs[2], 0, False
        while not done:
            pulses = policy.step_pulses(prev_angle, angle, steps)
            counts = culture.run(WINDOW_MS, constant=sensory_input(angle), pulses=pulses)
            action = decode(counts, rng)
            obs, _, term, trunc, _ = env.step(action)
            prev_angle, angle = angle, obs[2]
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
RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")


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
