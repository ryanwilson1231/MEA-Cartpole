"""
Method 2: set the success bar from the culture's own baseline (Pimashkin 2013).

How it works
  1. Calibration: play the first CALIBRATION_EPISODES episodes with no feedback and
     record how long each one lasts.
  2. The success bar is the 85th percentile of those lengths (top 15%).
  3. From then on, at the end of each episode:
       length above the bar  -> success: REST. The default feedback stimulus is
                                 switched off for the whole next episode.
       length at or below it -> failure: BURST (5 pulses at 100 per second on the
                                 FEEDBACK channels). The default feedback stimulus
                                 stays on.
  The reward and penalty are the same as in method 1; only how success is judged
  changes (a per culture bar instead of a fixed rule).

Conditions
  null    no feedback (control)
  method  the above
  sham    success decided by a coin flip with the same expected rate (15%)

Run:  python method2_percentile_bar.py --episodes 40 --seeds 3
"""
import argparse

import numpy as np

from common import FeedbackPolicy, FEEDBACK, PULSE_CURRENT, burst, run_experiment

CALIBRATION_EPISODES = 15
PERCENTILE = 85
TONIC_PULSES_PER_WINDOW = 1


class PercentileBar(FeedbackPolicy):
    def __init__(self, seed, sham=False):
        self.name = "sham" if sham else "method"
        self.sham = sham
        self.rng = np.random.default_rng(20_000 + seed)
        self.history = []
        self.bar = None
        self.resting = False        # True during the episode after a success

    def calibrating(self):
        return len(self.history) < CALIBRATION_EPISODES

    def step_pulses(self, prev_angle, angle, step):
        if self.calibrating() or self.resting:
            return []
        onsets = self.rng.uniform(0, 90, TONIC_PULSES_PER_WINDOW)
        return [(tuple(FEEDBACK), float(t), PULSE_CURRENT) for t in onsets]

    def end_episode(self, culture, length):
        self.history.append(length)
        if len(self.history) == CALIBRATION_EPISODES:
            self.bar = float(np.percentile(self.history, PERCENTILE))
            print(f"  [{self.name}] success bar = {self.bar:.1f} steps", flush=True)
            return
        if self.calibrating():
            return
        if self.sham:
            success = bool(self.rng.random() < (100 - PERCENTILE) / 100)
        else:
            success = length > self.bar
        self.resting = success
        if not success:
            culture.idle(100, pulses=burst(FEEDBACK))


def conditions():
    return {
        "null": lambda seed: FeedbackPolicy(),
        "m2_method": lambda seed: PercentileBar(seed),
        "m2_sham": lambda seed: PercentileBar(seed, sham=True),
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=int, default=40)
    ap.add_argument("--seeds", type=int, default=3)
    args = ap.parse_args()
    run_experiment(conditions(), args.seeds, args.episodes)
