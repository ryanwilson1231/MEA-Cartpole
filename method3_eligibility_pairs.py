"""
Method 3: learn which pair of electrodes to stimulate after a failed episode
(Robbins et al. 2026, cortical organoids).

How it works
  * The pole angle goes to the INPUT electrodes (bottom row) all the time, as in the other methods.
  * The training pool is the 6 FEEDBACK channels (row 5), so there are 15 possible pairs.
  * At the end of an episode, a training pattern is delivered ONLY IF the last 5
    episodes did not beat the last 20 (performance is not improving). Before there
    are 20 episodes of history, a pattern is delivered every time.
  * The pattern is a pair of electrodes: paired pulses 10 ms apart, repeated at
    10 Hz for 300 ms.
  * Each pair has a value V (starts at the floor) and an eligibility trace E.
    After every episode:
        V <- V + alpha * (R - V) * E      R = episode length in steps
        E <- gamma * E                    traces fade
        then a new pair is picked with probability proportional to V,
        and its E is increased by 1 so it gets credit for the next episode.
  * Constants are the organoid paper's (alpha 0.3, gamma 0.3, floor 10). The paper
    measured R in seconds; here R is in game steps, so the floor of 10 is a guess.

Conditions (this ladder lets us ask whether the algorithm itself is needed)
  null         no training pattern (control)
  adaptive     the method above
  random_pair  a uniformly random pair each time, same gating
  fixed_pair   one pair chosen once at the start and always used, same gating

Run:  python method3_eligibility_pairs.py --episodes 40 --seeds 3
"""
import argparse
from itertools import combinations

import numpy as np

from common import FeedbackPolicy, FEEDBACK, PULSE_CURRENT, run_experiment

ALPHA, GAMMA, V_FLOOR = 0.3, 0.3, 10.0
SHORT, LONG = 5, 20


def pair_pulses(pair):
    """Paired pulses, 10 ms apart, repeated at 10 Hz for 300 ms."""
    a, b = FEEDBACK[pair[0]], FEEDBACK[pair[1]]
    pulses = []
    for rep in range(3):
        t = rep * 100.0
        pulses.append(((a,), t, PULSE_CURRENT))
        pulses.append(((b,), t + 10.0, PULSE_CURRENT))
    return pulses


class EligibilityPairs(FeedbackPolicy):
    def __init__(self, seed, mode="adaptive"):
        self.name = mode
        self.mode = mode
        self.rng = np.random.default_rng(30_000 + seed)
        self.pairs = list(combinations(range(len(FEEDBACK)), 2))
        self.V = np.full(len(self.pairs), V_FLOOR)
        self.E = np.zeros(len(self.pairs))
        self.history = []
        self.fixed = int(self.rng.integers(len(self.pairs)))

    def _choose(self):
        if self.mode == "adaptive":
            return int(self.rng.choice(len(self.pairs), p=self.V / self.V.sum()))
        if self.mode == "fixed_pair":
            return self.fixed
        return int(self.rng.integers(len(self.pairs)))     # random_pair

    def end_episode(self, culture, length):
        self.history.append(length)
        if self.mode == "adaptive":
            self.V = np.maximum(V_FLOOR, self.V + ALPHA * (length - self.V) * self.E)
            self.E *= GAMMA
        h = self.history
        not_improving = len(h) < LONG or np.mean(h[-SHORT:]) <= np.mean(h[-LONG:])
        if not_improving:
            k = self._choose()
            culture.idle(300, pulses=pair_pulses(self.pairs[k]))
            if self.mode == "adaptive":
                self.E[k] += 1.0


def conditions():
    return {
        "null": lambda seed: FeedbackPolicy(),
        "adaptive": lambda seed: EligibilityPairs(seed, "adaptive"),
        "random_pair": lambda seed: EligibilityPairs(seed, "random_pair"),
        "fixed_pair": lambda seed: EligibilityPairs(seed, "fixed_pair"),
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=int, default=40)
    ap.add_argument("--seeds", type=int, default=3)
    args = ap.parse_args()
    run_experiment(conditions(), args.seeds, args.episodes)
