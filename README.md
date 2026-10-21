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
| `Saline-Test/` | Saline test kit: artifact removers, saline benchmark (pivot table), UCSC-style mapping, saline stimulation protocol (Abbas, Oct 21 2026) |
