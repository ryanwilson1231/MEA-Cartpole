"""
CartPole closed loop on the MEA through the C# spike server.

Run on the rig:
  1. SpikeLayerApp.exe --serve
  2. python run_closed_loop.py <label>
"""
import argparse
import os
import re
import sys
import time
from datetime import datetime

import numpy as np
import gymnasium as gym

from encoder import Encoder
from feedback import choose_action

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "Latency-Tests", "csharp", "SpikeLayerApp"))
import spike_client  # noqa: E402

GAMES = 20
REST_BETWEEN_GAMES_S = 2.0


def session_name(label):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", label):
        raise ValueError(f"invalid label {label!r}: use letters, digits, _ - .")
    return datetime.now().strftime("%Y-%m-%d_%H%M") + "_" + label


def to_halves(half, wave):
    amplitudes, durations, _ = wave
    pairs = list(zip(amplitudes, durations))
    if half == "left":
        return pairs, []
    if half == "right":
        return [], pairs
    raise ValueError(f"unexpected half {half!r}")


def play_game(env, encoder, episode, window):
    observation, _ = env.reset()
    encoder.new_game()
    last_action = None
    step, done = 0, False

    while not done:
        half, wave = encoder.step(observation, last_action)
        # TODO: validate(wave) once encoder.py has it
        left, right = to_halves(half, wave)

        first_sample, counts = spike_client.play_and_read(window, left, right)
        action = int(choose_action(np.array(counts)))

        observation, _, terminated, truncated, _ = env.step(action)
        # TODO: logger.log_step(episode, step, window, first_sample, observation, action, counts)

        last_action = action
        window += 1
        step += 1
        done = terminated or truncated

    return step, window


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("label")
    parser.add_argument("--games", type=int, default=GAMES)
    parser.add_argument("--rest", type=float, default=REST_BETWEEN_GAMES_S)
    args = parser.parse_args()

    name = session_name(args.label)
    env = gym.make("CartPole-v1")
    encoder = Encoder()
    window = 0  # session-wide window ID sent to the server; never reset
    episodes = []

    spike_client.start_session(name)
    try:
        for episode in range(args.games):
            if episode > 0:
                time.sleep(args.rest)
            first_window = window
            steps, window = play_game(env, encoder, episode, window)
            episodes.append((episode, steps, first_window))
            print(f"Episode {episode + 1}/{args.games}: {steps} steps")
    finally:
        spike_client.close()
        env.close()
        if episodes:
            os.makedirs("sessions", exist_ok=True)
            path = os.path.join("sessions", name + "_episodes.csv")
            np.savetxt(path, episodes, fmt="%d", delimiter=",",
                       header="episode,steps,first_window", comments="")


if __name__ == "__main__":
    main()
