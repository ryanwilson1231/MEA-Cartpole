"""
Method 1: stop stimulating when it goes well, send a short burst when the pole falls.
(Shahaf and Marom 2001; Le Feber 2010; paired organoids 2025.)

How it works
  * A low level feedback stimulus plays on the FEEDBACK channels by default.
  * Whenever the last step was a success, that stimulus is removed for the next
    window. This is the "reward": silence, not a positive signal. It carries no
    hint about which way to push, so it is evaluative by construction.
  * When the pole falls (end of episode), a short burst of 5 pulses at 100 per
    second goes to the same FEEDBACK electrodes (row 5). This is the "penalty".
  * State information (pole angle) goes only to the INPUT electrodes (bottom row), so the
    rest and burst never interfere with it.

What counts as a success here (our choice, easy to change)
  The pole moved closer to upright since the last step: |angle| got smaller.

Conditions
  null        no feedback at all (control)
  rest_burst  the method
  rest_only   rest on success, no burst on fall (is the burst needed?)
  sham        same kinds of stimulation, but the rest is decided by a coin flip
              instead of by the pole (is it the contingency or just extra stimulation?)

Run:  python method1_rest_and_burst.py --episodes 40 --seeds 3
"""
import argparse

import numpy as np

from common import FeedbackPolicy, FEEDBACK, PULSE_CURRENT, burst, run_experiment

TONIC_PULSES_PER_WINDOW = 1   # the default feedback stimulus that "rest" removes


class RestAndBurst(FeedbackPolicy):
    def __init__(self, seed, use_burst=True, sham=False):
        self.name = "sham" if sham else ("rest_burst" if use_burst else "rest_only")
        self.use_burst = use_burst
        self.sham = sham
        self.rng = np.random.default_rng(10_000 + seed)

    def _success(self, prev_angle, angle, step):
        if step == 0:
            return False
        if self.sham:
            return bool(self.rng.random() < 0.5)       # decoupled from the pole
        return abs(angle) < abs(prev_angle)

    def step_pulses(self, prev_angle, angle, step):
        if self._success(prev_angle, angle, step):
            return []                                   # rest: remove the stimulus
        onsets = self.rng.uniform(0, 90, TONIC_PULSES_PER_WINDOW)
        return [(tuple(FEEDBACK), float(t), PULSE_CURRENT) for t in onsets]

    def end_episode(self, culture, length):
        if self.use_burst:
            culture.idle(100, pulses=burst(FEEDBACK))   # penalty on the fall


def conditions():
    from common import FeedbackPolicy as Null
    return {
        "null": lambda seed: Null(),
        "rest_burst": lambda seed: RestAndBurst(seed, use_burst=True),
        "rest_only": lambda seed: RestAndBurst(seed, use_burst=False),
        "m1_sham": lambda seed: RestAndBurst(seed, use_burst=True, sham=True),
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=int, default=40)
    ap.add_argument("--seeds", type=int, default=3)
    args = ap.parse_args()
    run_experiment(conditions(), args.seeds, args.episodes)
