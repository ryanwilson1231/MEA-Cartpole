"""
Method 3 variations: the eligibility pair method (Robbins et al. 2026) with five optional changes.

Each change is a switch, so we can test them one at a time and together.
The original method stays untouched in method3_eligibility_pairs.py.

The five variations
  fair      Fair tryouts. Until every pair has been delivered TRIES times, the pair is picked at
            random from the pairs tried least. Only after that do the values steer the choice.
            Stops an early lucky pair from taking over before the others got a turn.
  baseline  Baseline. A pair is judged against typical play, not against zero. The target for V
            becomes V_FLOOR + (length - mean of the earlier episodes). Better than usual raises
            V above the floor, worse than usual pushes it back down to the floor.
  replacing Replacing trace. When a pair is used its trace is SET to 1, not increased by 1, so
            using the same pair again and again does not pile up credit.
  timefade  Time based fade. The trace fades by time passed, not by episode: after an episode of
            n steps it is multiplied by GAMMA ** (n / REF_STEPS). A long episode fades it more.
  thompson  Thompson sampling. For each pair we keep what the episode that followed its use scored.
            To choose, we draw one random sample of "how good is this pair" for every pair from
            its belief (a bell curve that narrows as the pair is tried more) and use the highest.
            Replaces the "probability proportional to V" rule. V and E are not used in this mode.
  sham      Contingency sham (a yoked control). Replays the EXACT schedule the v_adaptive run of the
            same seed used: the same pairs at the same episodes, but it ignores game results.
            If v_adaptive does better than sham, the benefit comes from the contingency, not from the
            stimulation itself. Run v_adaptive first (the conditions dict does this by order).

Everything else (gating, pulse pattern, constants, floor) is the same as the original method.
The floor of 10 is still a guess, because the paper measured R in seconds and here R is in steps.

Conditions
  null          no training pattern (control)
  v_adaptive    the method with no switches on (matches the original, plus it records its schedule)
  v_fair, v_baseline, v_replacing, v_timefade, v_thompson     one switch each
  v_combined    fair + baseline + replacing + timefade together
  v_sham        replay of the v_adaptive schedule, ignoring results

Run:  python method3_variations.py --episodes 40 --seeds 3
"""
import argparse
import json
import os
from itertools import combinations

import numpy as np

from common import FeedbackPolicy, FEEDBACK, PULSE_CURRENT, RESULTS_DIR, run_experiment

ALPHA, GAMMA, V_FLOOR = 0.3, 0.3, 10.0
SHORT, LONG = 5, 20
TRIES = 2          # fair tryouts: each pair is delivered at least this many times first
REF_STEPS = 20.0   # time based fade: the length of a typical episode, in steps
PRIOR_SD = 10.0    # Thompson sampling: starting uncertainty about a pair, in steps


def pair_pulses(pair):
    """Paired pulses, 10 ms apart, repeated at 10 Hz for 300 ms."""
    a, b = FEEDBACK[pair[0]], FEEDBACK[pair[1]]
    pulses = []
    for rep in range(3):
        t = rep * 100.0
        pulses.append(((a,), t, PULSE_CURRENT))
        pulses.append(((b,), t + 10.0, PULSE_CURRENT))
    return pulses


def schedule_path(seed):
    return os.path.join(RESULTS_DIR, f"m3_schedule_s{seed}.json")


class EligibilityVariants(FeedbackPolicy):
    def __init__(self, seed, name, fair=False, baseline=False, replacing=False,
                 timefade=False, thompson=False, sham=False, record_schedule=False):
        self.name = name
        self.seed = seed
        self.fair, self.baseline, self.replacing = fair, baseline, replacing
        self.timefade, self.thompson, self.sham = timefade, thompson, sham
        self.record_schedule = record_schedule
        self.rng = np.random.default_rng(30_000 + seed)
        self.pairs = list(combinations(range(len(FEEDBACK)), 2))
        n = len(self.pairs)
        self.V = np.full(n, V_FLOOR)
        self.E = np.zeros(n)
        self.tries = np.zeros(n, dtype=int)
        self.outcomes = [[] for _ in range(n)]   # Thompson: lengths of the episode after each use
        self.history = []
        self.pending = None                      # the pair delivered after the last episode
        self.schedule = {}                       # episode index -> pair index
        self.replay = None
        if sham:
            path = schedule_path(seed)
            if not os.path.exists(path):
                raise FileNotFoundError(
                    f"{path} not found. Run v_adaptive for seed {seed} first "
                    "(the conditions dict runs it before v_sham).")
            with open(path) as f:
                self.replay = {int(k): v for k, v in json.load(f).items()}

    # ------------------------------------------------------------------ choosing a pair
    def _thompson_pick(self):
        prior_mean = float(np.mean(self.history)) if self.history else V_FLOOR
        samples = np.empty(len(self.pairs))
        for k, obs in enumerate(self.outcomes):
            n = len(obs)
            mean = (prior_mean + sum(obs)) / (1 + n)     # prior counts as one observation
            sd = PRIOR_SD / np.sqrt(1 + n)
            samples[k] = self.rng.normal(mean, sd)
        return int(np.argmax(samples))

    def _choose(self):
        if self.fair and self.tries.min() < TRIES:
            least = np.flatnonzero(self.tries == self.tries.min())
            return int(self.rng.choice(least))
        if self.thompson:
            return self._thompson_pick()
        return int(self.rng.choice(len(self.pairs), p=self.V / self.V.sum()))

    # ------------------------------------------------------------------ learning
    def _learn(self, length):
        prior = self.history[:-1]                 # episodes before this one
        if self.thompson:
            if self.pending is not None:
                self.outcomes[self.pending].append(length)
            return
        if self.baseline:
            typical = float(np.mean(prior)) if prior else float(length)
            target = V_FLOOR + (length - typical)
        else:
            target = length
        self.V = np.maximum(V_FLOOR, self.V + ALPHA * (target - self.V) * self.E)
        fade = GAMMA ** (length / REF_STEPS) if self.timefade else GAMMA
        self.E *= fade

    def end_episode(self, culture, length):
        ep = len(self.history)                    # index of the episode that just ended
        self.history.append(length)
        h = self.history
        if not self.sham:
            self._learn(length)
        not_improving = len(h) < LONG or np.mean(h[-SHORT:]) <= np.mean(h[-LONG:])

        if self.sham:
            k = self.replay.get(ep)               # same pair, same episode as v_adaptive
            deliver = k is not None
        else:
            deliver = not_improving
            k = self._choose() if deliver else None
        self.pending = k
        if deliver:
            culture.idle(300, pulses=pair_pulses(self.pairs[k]))
            self.tries[k] += 1
            if not self.sham and not self.thompson:
                self.E[k] = 1.0 if self.replacing else self.E[k] + 1.0
            self.schedule[ep] = k
        if self.record_schedule:
            os.makedirs(RESULTS_DIR, exist_ok=True)
            with open(schedule_path(self.seed), "w") as f:
                json.dump(self.schedule, f)


def conditions():
    return {
        "null": lambda seed: FeedbackPolicy(),
        "v_adaptive": lambda seed: EligibilityVariants(seed, "v_adaptive", record_schedule=True),
        "v_fair": lambda seed: EligibilityVariants(seed, "v_fair", fair=True),
        "v_baseline": lambda seed: EligibilityVariants(seed, "v_baseline", baseline=True),
        "v_replacing": lambda seed: EligibilityVariants(seed, "v_replacing", replacing=True),
        "v_timefade": lambda seed: EligibilityVariants(seed, "v_timefade", timefade=True),
        "v_thompson": lambda seed: EligibilityVariants(seed, "v_thompson", thompson=True),
        "v_combined": lambda seed: EligibilityVariants(
            seed, "v_combined", fair=True, baseline=True, replacing=True, timefade=True),
        "v_sham": lambda seed: EligibilityVariants(seed, "v_sham", sham=True),
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=int, default=40)
    ap.add_argument("--seeds", type=int, default=3)
    args = ap.parse_args()
    run_experiment(conditions(), args.seeds, args.episodes)
