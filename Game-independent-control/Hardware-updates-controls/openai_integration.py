import gym
import numpy as np
import time
# Rest uses elapsed recording time rather than game episodes.

class IntegratedOpenAIGymAPI:
    def __init__(self, mea_interface):
        """Initialize the OpenAI Gym API with the integrated MEA interface."""
        self.env = None if mea_interface.control_mode == 'rest' else gym.make('CartPole-v1')
        # Rest records spontaneous activity without creating a game.
        self.mea_interface = mea_interface
        self.total_reward = 0

    def set_control_mode(self, control_mode):
        self.mea_interface.set_control_mode(control_mode)
        # Share the stimulation policy with the existing MEA interface.
    
    def initialize_training(self):
        """Initialize the training environment."""
        if self.mea_interface.control_mode == 'rest':
            return None
        if self.env is None:
            self.env = gym.make('CartPole-v1')
        # Reset the game only in game modes, including when leaving Rest.
        self.mea_interface.set_stimulation_phase('game')
        # Reopen the original in-game stimulation policy for each new episode.
        state, _ = self.env.reset()
        self.total_reward = 0
        return state
    
    def run_single_frame(self, client_socket=None):
        """Run a single frame of the CartPole environment."""
        # Direct hardware controls use the existing frame method without a socket.
        # Get neural data from the MEA
        raw_neural_buffer = self.mea_interface.read_neural_data_buffer()
        if self.mea_interface.control_mode == 'rest':
            self.rest_buffer = raw_neural_buffer
            return None, None, 0, False
        # Rest reads spontaneous activity without decoding or updating CartPole.
        
        # Extract action from neural activity
        neuron_action = self.mea_interface.extract_neuron_action(raw_neural_buffer)
        
        # Take a step in the environment
        observation, reward, terminated, truncated, info = self.env.step(neuron_action)
        
        # Update total reward
        self.total_reward += reward
        
        # Return relevant information
        return observation[2], observation[3], reward, terminated or truncated

    def run_rest(self, duration=60, sample_interval=0.05):
        self.set_control_mode('rest')
        end_time = time.monotonic() + duration
        while time.monotonic() < end_time:
            self.run_single_frame()
            remaining = end_time - time.monotonic()
            if remaining > 0:
                time.sleep(min(sample_interval, remaining))
        # Acquisition is already running; sample its buffer for a fixed wall-clock duration.

