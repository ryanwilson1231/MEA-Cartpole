| Control	| Brian2-Path	| Hardware-Pythonnet-Path |
|------|------|------|
| Method #1: Silent	| Disable stimulation and reward-modulated STDP; preserve simulation and decoding	| Skip stimulation; preserve recording, decoding and game updates |
| Method #2: Sensory only	| Keep state encoding, disable performance-dependent random noise and reward modulation	| Keep state-encoding waveform, remove performance-dependent waveform switching |
| Method #3: Rest	| Run spontaneous neural simulation without stimulation or reward modulation | Record spontaneous activity without sending stimulation; optionally decode into a virtual game |
