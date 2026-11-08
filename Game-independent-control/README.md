# Game-Independent Controls
Modify the Main Game code to decouple feedback stimulation from game outcomes, then compare training performance with that under outcome-dependent feedback to assess the role of reward/punishment contingency in learning. 

## Control Methods (modified version from Main Game Codes)
| Control	| Brian2-Path --> Brian2-Path-Controls	| Hardware-Pythonnet-Path --> Hardware-Pythonnet-Path-Controls |
|------|------|------|
| Method #1: Silent	| Disable stimulation and reward-modulated STDP; preserve simulation and decoding	| Skip stimulation; preserve recording, decoding and game updates |
| Method #2: Sensory only	| Keep state encoding, disable performance-dependent random noise and reward modulation	| Keep state-encoding waveform, remove performance-dependent waveform switching |
| Method #3: Rest	| Run spontaneous neural simulation without stimulation or reward modulation | Record spontaneous activity without sending stimulation; optionally decode into a virtual game |

## Three control modes (full Brian2 and hardware paths)

The existing integration and stimulation functions now accept `control_mode`.
The default, `training`, preserves the original feedback policy. Each addition
has a short comment next to the changed code explaining its purpose.

| Mode | Game and decoding | Stimulation | Brian2 reward-modulated STDP |
|------|-------------------|-------------|------------------------------|
| `training` | Original game loop | Original state waveform / performance-dependent noise | Original reward trace |
| `silent` | Keep recording, decoding and game updates | None | Off |
| `sensory_only` | Keep recording, decoding and game updates | Always use the original state-encoding waveform; no performance-dependent noise or waveform switching | Off |
| `rest` | Record / simulate activity for a fixed duration; no decoding, game reset or game updates | None | Off |

Silent retains the game loop; Rest measures spontaneous activity without it.
Game rewards can still be recorded as performance metrics in Silent and
Sensory-only, but they do not modulate Brian2 synaptic weights. Hardware controls
change delivered stimulation, not the cells' intrinsic plasticity.
Sensory-only retains the original waveform parameters and channel-selection rule.

### Run from the repository root

In Windows PowerShell, make the existing shared `spike.py` and `square.py`
modules available to the two full paths:

```powershell
$env:PYTHONPATH = (Get-Location).Path
python Brian2-Path/brian_integration.py --control-mode silent --episodes 5
python Brian2-Path/brian_integration.py --control-mode sensory_only --episodes 5
python Brian2-Path/brian_integration.py --control-mode rest --rest-duration 60
```

On the Windows MEA setup, use the same options with the original hardware runner:

```powershell
python Hardware-Pythonnet-Path/run_cartpole.py --control-mode silent --episodes 5
python Hardware-Pythonnet-Path/run_cartpole.py --control-mode sensory_only --episodes 5
python Hardware-Pythonnet-Path/run_cartpole.py --control-mode rest --rest-duration 60
```

`--rest-duration` is in **seconds**: simulated time for Brian2 and wall-clock
recording time for hardware. Silent keeps the original Brian2 110 ms per game
frame (10 ms recording plus the 100 ms stimulation interval with input off).
Brian2 plots the session already recorded, without adding more simulation time.

### Select or switch modes in Python

```python
integration = Brian2CartPoleIntegration(control_mode='sensory_only')
integration.train(num_episodes=5)

# Use these on an active integration before continuing its frame loop.
integration.set_control_mode('silent')
integration.run_rest(duration_ms=10000)
```

The hardware interface accepts `IntegratedMEAInterface(control_mode='silent')`;
its existing Gym integration exposes `set_control_mode(...)` and
`run_rest(duration=10)` (seconds), with acquisition started by the existing runner.
Call `initialize_training()` before resuming a game after Rest.

Changing a Brian2 mode clears the previous injected current and reward trace,
while retaining synaptic weights and recorded activity. Rest uses the original
network with no added background drive; the network may therefore stay quiescent.
Brian2's existing monitors retain spikes and population rate. `rest_buffer` holds
only the latest sampled buffer; hardware Rest adds no new raw-data export format.

