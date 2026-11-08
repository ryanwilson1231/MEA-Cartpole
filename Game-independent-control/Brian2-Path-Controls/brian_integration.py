# brian_integration.py
import matplotlib.pyplot as plt
from brian_simulator import Brian2MEASimulator
import brian2 as b2
from brian2 import prefs
prefs.codegen.target = "numpy"
import numpy as np
import gymnasium as gym

class Brian2CartPoleIntegration:
    def __init__(self, control_mode='training'):
        self.env = None if control_mode == 'rest' else gym.make('CartPole-v1')
        self.mea_simulator = Brian2MEASimulator(num_channels=60, buffer_size=100,
                                              control_mode=control_mode)
        # Rest starts without a game; the existing simulator owns the mode switches.
        self.mea_simulator.connect_to_device()

        self.total_reward = 0
        self.episode_rewards = []
        self.episode_lengths = []
        self.current_episode_length = 0

    def set_control_mode(self, control_mode):
        self.mea_simulator.set_control_mode(control_mode)
        # Use the same mode for the game loop and the stimulation mechanism.

    def initialize_training(self):
        if self.mea_simulator.control_mode == 'rest':
            self.mea_simulator.start_recording()
            return None
        if self.env is None:
            self.env = gym.make('CartPole-v1')
        # Reset CartPole only for game modes, including when leaving Rest.
        state, _ = self.env.reset()
        self.total_reward = 0
        self.current_episode_length = 0
        self.mea_simulator.start_recording()
        return state

    def run_single_frame(self):
        self.mea_simulator.run_simulation(10)
        buffer = self.mea_simulator.read_neural_data_buffer()
        if self.mea_simulator.control_mode == 'rest':
            self.mea_simulator.run_simulation(100)
            self.rest_buffer = self.mea_simulator.read_neural_data_buffer()
            return None, None, 0, False
        # Rest advances the same 110 ms interval without decoding or stepping a game.
        action = self.mea_simulator.extract_neuron_action(buffer)
        obs, reward, terminated, truncated, _ = self.env.step(action)

        self.total_reward += reward
        self.current_episode_length += 1

        pole_angle = obs[2]
        pole_angular_velocity = obs[3]
        self.mea_simulator.stimulate_neurons(pole_angle, pole_angular_velocity, reward)

        done = terminated or truncated
        if done:
            self.episode_rewards.append(self.total_reward)
            self.episode_lengths.append(self.current_episode_length)

        return pole_angle, pole_angular_velocity, reward, done

    def run_rest(self, duration_ms=60000, step_ms=110):
        self.set_control_mode('rest')
        self.mea_simulator.start_recording()
        elapsed_ms = 0
        while elapsed_ms < duration_ms:
            interval_ms = min(step_ms, duration_ms - elapsed_ms)
            self.mea_simulator.run_simulation(interval_ms)
            self.rest_buffer = self.mea_simulator.read_neural_data_buffer()
            elapsed_ms += interval_ms
        # Record spontaneous activity for a fixed duration, independent of game results.

    def train(self, num_episodes=100, render=False, rest_duration_ms=60000):
        if self.mea_simulator.control_mode == 'rest':
            self.run_rest(duration_ms=rest_duration_ms)
            return
        # Rest uses elapsed simulation time instead of episode termination.
        for episode in range(num_episodes):
            state = self.initialize_training()
            done = False

            while not done:
                if render:
                    self.env.render()
                _, _, _, done = self.run_single_frame()

            print(f"Episode {episode+1}/{num_episodes}, Reward: {self.total_reward}, Length: {self.current_episode_length}")

        self.env.close()
        self.plot_training_results()

    def plot_training_results(self):
        plt.figure(figsize=(12, 5))
        plt.subplot(1, 2, 1)
        plt.plot(self.episode_rewards)
        plt.title('Episode Rewards')
        plt.xlabel('Episode')
        plt.ylabel('Total Reward')

        plt.subplot(1, 2, 2)
        plt.plot(self.episode_lengths)
        plt.title('Episode Lengths')
        plt.xlabel('Episode')
        plt.ylabel('Steps')

        plt.tight_layout()
        plt.show()

    def visualize_network_activity(self, duration=500):
        self.mea_simulator.run_simulation(duration)
        plt.figure(figsize=(12, 8))
        plt.subplot(2, 1, 1)
        plt.plot(self.mea_simulator.spike_monitor.t/b2.ms, self.mea_simulator.spike_monitor.i, '.k', markersize=2)
        # Use the imported Brian2 units when viewing activity from any control mode.
        plt.title('Spike Raster Plot')
        plt.xlabel('Time (ms)')
        plt.ylabel('Neuron Index')

        plt.subplot(2, 1, 2)
        plt.plot(self.mea_simulator.rate_monitor.t/b2.ms, self.mea_simulator.rate_monitor.rate/b2.Hz)
        # Keep time and firing-rate units explicit for the same activity view.
        plt.title('Population Firing Rate')
        plt.xlabel('Time (ms)')
        plt.ylabel('Firing Rate (Hz)')

        plt.tight_layout()
        plt.show()

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--control-mode', choices=['training', 'silent', 'sensory_only', 'rest'],
                        default='training')
    parser.add_argument('--episodes', type=int, default=100)
    parser.add_argument('--rest-duration', type=float, default=60,
                        help='Rest duration in seconds of simulated time')
    args = parser.parse_args()
    # Select a control at the existing entry point; training remains the default.
    integration = Brian2CartPoleIntegration(control_mode=args.control_mode)
    integration.train(num_episodes=args.episodes, render=False,
                      rest_duration_ms=args.rest_duration * 1000)
    # Convert the Rest duration to the simulator's existing millisecond units.
    integration.visualize_network_activity(duration=0)
    # Plot the recorded session without extending its selected control or Rest duration.

