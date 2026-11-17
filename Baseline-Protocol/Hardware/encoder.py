import random
import numpy as np

THETA_MAX = 0.2095   # rad (12 degrees): the game ends past this angle
OMEGA_MAX = 2.0      # rad/s
F_MIN, F_MAX = 4, 40            # Hz
A_MIN_UV = 50_000               # 50 mV
A_MAX_UV = 100_000              # 100 mV
A_LIMIT_UV = 300_000            # never send anything above this
PHASE_US = 200                  # each half of a pulse, in microseconds
STEP_MS = 100                   # one game step
BAD_GAME_STEPS = 20             # a game shorter than this is bad

class Encoder:
    def __init__(self):
        self.ms_since_last_pulse = None  # timing carried between steps (step 4)

    def new_game(self):
        """Call when a game starts. Resets the timing."""
        self.ms_since_last_pulse = None

    def step(self, observation, last_action):
        """Steps 1-5. Returns (half, wave).
        half: "left" or "right"
        wave: (amplitudes_uV, durations_us, active), three lists"""
        pass  
        
        theta = observation[2]   # pole angle (rad); negative = leaning left
        omega = observation[3]   # pole turning speed (rad/s); negative = turning left# steps 1-5 go here

        theta_n = np.clip(theta / THETA_MAX, -1, 1)
        omega_n = np.clip(omega / OMEGA_MAX, -1, 1)

        f = F_MIN + (F_MAX - F_MIN) * (theta_n + 1) / 2 #(in Hz)
        A = A_MIN_UV + (A_MAX_UV - A_MIN_UV) * (omega_n + 1) / 2 #(in μV)

                # Step 4: pulse times (in ms, kept as decimals until step 5)
        gap = 1000 / f                      # ms between pulses
        pulse_ms = 2 * PHASE_US / 1000      # a pulse lasts 0.4 ms

        if self.ms_since_last_pulse is None:
            t = 0                           # first step of a game: pulse right away
        else:
            t = max(0, gap - self.ms_since_last_pulse)

        onsets = []
        while t <= STEP_MS - pulse_ms:      # the pulse must fit inside the step
            onsets.append(t)
            t += gap

        if onsets:
            self.ms_since_last_pulse = STEP_MS - onsets[-1]
        else:
            self.ms_since_last_pulse += STEP_MS

        if last_action is None:
            half = random.choice(["left", "right"])
        else:
            half = "left" if last_action == 0 else "right"

        amp = int(round(A))
        amplitudes, durations, active = [], [], []
        cursor = 0

        for t_ms in onsets:
            onset_us = int(round(t_ms * 1000 / 20) * 20)

            gap_us = onset_us - cursor
            if gap_us > 0:                  # silent block before this pulse
                amplitudes.append(0)
                durations.append(gap_us)
                active.append(0)

            amplitudes += [amp, -amp]       # +A then -A
            durations += [PHASE_US, PHASE_US]
            active += [1, 1]
            cursor = onset_us + 2 * PHASE_US

        tail = STEP_MS * 1000 - cursor      # silent block to reach 100,000 μs
        if tail > 0:
            amplitudes.append(0)
            durations.append(tail)
            active.append(0)

        return half, (amplitudes, durations, active)

    def after_game(self, steps):
        """Returns None for a good game, or (left_wave, right_wave) of noise."""
        pass  # built last


def validate(wave):
    """Step 6. Raises ValueError if the wave is unsafe."""
    pass  # built last

if __name__ == "__main__":
    # Step 1 check: play one random game and print theta and omega
    import gymnasium as gym

    env = gym.make("CartPole-v1")
    obs, _ = env.reset()
    done = False
    while not done:
        theta = obs[2]
        omega = obs[3]
        print(f"theta={theta:+.3f}  omega={omega:+.3f}")
        obs, _, terminated, truncated, _ = env.step(env.action_space.sample())
        done = terminated or truncated

if __name__ == "__main__":
    enc = Encoder()
    enc.new_game()
    half, (a, d, act) = enc.step([0, 0, 0.0, 0.0], 0)
    print(half)
    print(a)
    print(d)
    print(act)

    assert a   == [75000, -75000, 0, 75000, -75000, 0, 75000, -75000, 0]
    assert d   == [200, 200, 45060, 200, 200, 45040, 200, 200, 8700]
    assert act == [1, 1, 0, 1, 1, 0, 1, 1, 0]
    assert sum(d) == 100_000
    print("step 5 OK")