"""
Baseline closed loop, simulated with Brian2 (no hardware needed).

Each game step:
  1. Look at the pole.
  2. Stimulate: predictable if it's balanced, unpredictable if not.
  3. Listen to the neurons while the stimulation plays.
  4. Turn spike counts into an action (left or right).
  5. Step CartPole with that action.

Every step is timed and saved to timings_<timestamp>.csv:
  sleep_ms  - time spent waiting on the clock (0 here: Brian2 runs as fast as it can;
              on hardware this is the 100 ms listen window)
  frame_ms  - time to get the window's spike counts (here: simulating 100 ms of neurons)
  stim_ms   - time to set up the stimulation
  total_ms  - the whole step, including the decode and env.step

Run:  python3 run_brian2.py
"""
import csv
import time
from datetime import datetime

import numpy as np
import gymnasium as gym
import matplotlib.pyplot as plt

from feedback import is_balanced, lean_side, choose_action
from simulated_mea import SimulatedMEA

EPISODES = 20
WINDOW_MS = 100   # how long each stimulate + listen step lasts
RENDER = False    # True opens a window showing the cart (slower)


def ms_since(t0):
    return (time.perf_counter() - t0) * 1000


def main():
    env = gym.make("CartPole-v1", render_mode="human" if RENDER else None)
    mea = SimulatedMEA()
    mea.connect()

    w_before = np.array(mea.synapses.w[:])
    print(f"mean synapse weight before: {w_before.mean():.4f}")

    episode_lengths = []
    timings = []
    for episode in range(EPISODES):
        observation, _ = env.reset()
        steps, done = 0, False

        while not done:
            t_step = time.perf_counter()
            pole_angle = observation[2]

            t = time.perf_counter()
            if is_balanced(pole_angle):
                mea.stimulate_predictable(lean_side(pole_angle))
            else:
                mea.stimulate_unpredictable()
            stim_ms = ms_since(t)

            sleep_ms = 0.0  # no real-time wait in the simulator

            t = time.perf_counter()
            spike_counts = mea.read_spike_counts(WINDOW_MS)
            frame_ms = ms_since(t)

            action = choose_action(spike_counts)
            observation, reward, terminated, truncated, _ = env.step(action)
            done = terminated or truncated
            steps += 1

            total_ms = ms_since(t_step)
            timings.append([episode + 1, steps, round(sleep_ms, 3), round(frame_ms, 3),
                            round(stim_ms, 3), round(total_ms, 3)])

        episode_lengths.append(steps)
        print(f"Episode {episode + 1}/{EPISODES}: {steps} steps")

    w_after = np.array(mea.synapses.w[:])
    print(f"mean synapse weight after:  {w_after.mean():.4f}  (change {w_after.mean() - w_before.mean():+.4f}, "
          f"{np.mean(w_after != w_before):.0%} of synapses changed)")

    mea.close()
    env.close()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    with open(f"timings_{timestamp}.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["episode", "step", "sleep_ms", "frame_ms", "stim_ms", "total_ms"])
        w.writerows(timings)

    t = np.array([row[2:] for row in timings])
    print(f"\nSaved timings_{timestamp}.csv ({len(timings)} steps)")
    print("mean per step:  sleep {:.2f} ms | frame {:.2f} ms | stim {:.2f} ms | total {:.2f} ms".format(*t.mean(axis=0)))
    print("worst step:     total {:.2f} ms".format(t[:, 3].max()))

    np.savetxt("episode_lengths.csv", episode_lengths, fmt="%d", header="steps", comments="")
    plt.plot(range(1, EPISODES + 1), episode_lengths, marker="o")
    plt.xlabel("Episode")
    plt.ylabel("Steps balanced")
    plt.title("Brian2 baseline")
    plt.show()


if __name__ == "__main__":
    main()
