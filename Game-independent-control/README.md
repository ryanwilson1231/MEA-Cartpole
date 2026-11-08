# MEA-closed-loop-neural-stimulation-and-recording

Neurotech@Berkeley MEA team. Neurons on a microelectrode array (MEA) play
CartPole in a closed loop: stimulation tells them where the pole is, and their
spikes decide which way to push the cart.

## New members: start here

Go to [`Baseline-Protocol/`](Baseline-Protocol/). It's the simplest working version of the
project, with a simulated version (Brian2, no hardware needed) and a hardware version
that follow the same steps. Its README explains the loop and how to run it.

## Repo layout

| Folder | What it is |
|--------|------------|
| `Baseline-Protocol/` | Simplified starting point: Brian2 and hardware versions side by side |
| `Brian2-Path/` | Full simulation: inhibition, synaptic scaling, reward-modulated STDP |
| `Hardware-Pythonnet-Path/` | Full hardware version for the MEA2100-Mini (pythonnet + `McsUsbNet.dll`) |
| `spike.py`, `square.py` | Spike detection and stimulation waveforms used by the full paths |

## Three control modes (full Brian2 and hardware paths)

The existing integration and stimulation functions accept `control_mode`.
A separate `stimulation_phase` distinguishes the running game from post-game
feedback. Short comments beside each addition explain its purpose.

| Mode | During a game | After each episode |
|------|---------------|--------------------|
| `training` | Original game and stimulation policy | Original terminal policy and original hardware inter-episode wait |
| `silent` | Original game and stimulation policy | Complete silence for `feedback_duration`: no sensory or reward/punishment stimulation, with activity recording continuing |
| `sensory_only` | State-encoding stimulation only | Continue sensory stimulation through the normal frame schedule and proceed directly to the next episode, with no programmed silence or inter-episode wait |
| `rest` | Read / simulate neural activity without a game | No sensory or reward/punishment stimulation throughout the recording |

### Phase handling

Silent keeps the original in-game behavior. Once `terminated` or `truncated`
becomes true, the integration enters the feedback phase **before** it can send
a terminal stimulation waveform. Brian2 clears held input current and reward
modulation, then simulates and records the entire Silent interval. The hardware
interface replaces previously programmed channel waveforms with zero output
through the original `send_stimulation` API, then blocks further output during
the interval. Data acquisition remains active. Starting the next episode
returns the phase to `game`.

Sensory-only always uses the original state-encoding waveform. It never selects
performance-dependent punishment noise or Brian2 reward modulation. It does not
enter Silent's feedback phase, clear the sensory input at episode boundaries,
or call the original one-second hardware inter-episode sleep. “No silence” means
no deliberately scheduled silent window. The original discrete waveform and
frame-acquisition timing remain in use.

Rest skips game creation, game reset, action decoding and game updates. It uses
the original recording / simulation mechanisms for a fixed duration.
Hardware modes control stimulus delivery, not the cells' intrinsic plasticity.

The original full paths combine state encoding and performance-based waveform
selection within each frame. Silent preserves that in-game policy. These edits
do not move Training's original feedback policy to a new post-game stage.

### Timing

`--feedback-duration` sets the Silent interval in **seconds**, defaulting to
`1.0`. This is a configurable implementation choice taken from the hardware
runner's original one-second inter-episode gap. The original Brian2 path had
no separate post-game gap. Its Silent terminal frame now uses this explicit
interval in place of the original 100 ms terminal stimulation.

`--rest-duration` is also in seconds. Brian2 uses simulated time for both
options and hardware uses wall-clock time. Training retains its original
behavior. Sensory-only ignores `--feedback-duration` and adds no post-game wait.
Brian2 plots the recorded session without adding simulation time.

### Run from the repository root

In Windows PowerShell, make the shared `spike.py` and `square.py` available:

```powershell
$env:PYTHONPATH = (Get-Location).Path
python Brian2-Path/brian_integration.py --control-mode silent --episodes 5 --feedback-duration 1
python Brian2-Path/brian_integration.py --control-mode sensory_only --episodes 5
python Brian2-Path/brian_integration.py --control-mode rest --rest-duration 60
```

On the Windows MEA setup, use the same options with the hardware runner:

```powershell
python Hardware-Pythonnet-Path/run_cartpole.py --control-mode silent --episodes 5 --feedback-duration 1
python Hardware-Pythonnet-Path/run_cartpole.py --control-mode sensory_only --episodes 5
python Hardware-Pythonnet-Path/run_cartpole.py --control-mode rest --rest-duration 60
```

### Select a mode in Python

```python
integration = Brian2CartPoleIntegration(
    control_mode='silent', feedback_duration_ms=1000
)
integration.train(num_episodes=5)
```

On an active integration, `set_control_mode(...)` changes the policy.
`initialize_training()` starts a new episode and restores the game phase.
For Rest, call `run_rest(duration_ms=10000)` on Brian2 or
`run_rest(duration=10)` on the hardware Gym integration after acquisition starts.
The runner handles all these transitions in normal use.

Changing a Brian2 mode clears previous injected current and reward modulation,
while retaining synaptic weights and recorded activity. Silent retains the
original reward-modulated STDP during a game and disables it during post-game
silence. Sensory-only and Rest keep reward modulation off throughout.
Rest adds no background drive, so the simulated network may stay quiescent.
Existing Brian2 monitors retain spikes and population rate. `rest_buffer` and
`feedback_buffer` retain the latest sampled buffer rather than a full raw-data
history. These changes add no new raw-data export format.
