# Hardware path — bug fixes

## Why this branch exists

While preparing the first saline runs we traced the whole hardware path and
reflected on `McsUsbNet.dll` directly. Several problems would have stopped a run
before any data was collected. This branch fixes them.

**None of this is verified on the rig yet.** It is verified to import, compile,
and resolve against the real DLL. The `latency-pythonnet` / `latency-csharp`
branches are how we confirm the rest.

---

## The four that would have stopped the run

### 1. The stimulation code called an API that does not exist

```python
from Mcs.Usb import CMcsUsbBStimNet          # ImportError - not in the DLL
factory = CMcsUsbFactoryNet()
self.bstim = factory.CreateBStim(usb_entries[0])   # no such method
```

`CMcsUsbBStimNet` is not in McsUsbNet.dll v5.1.36.0, and `CMcsUsbFactoryNet` is a
firmware-update utility with no `CreateBStim`. The import alone raises.

**Fixed:** rewritten against `CStimulusFunctionNet`, constructed directly from the
device. It also takes amplitude/duration *step pairs*, not a sampled waveform, so
`send_stimulation()` now converts each waveform sample into one step.

### 2. The DLL would not load at all

It was downloaded and sits under OneDrive, so Windows marks it and .NET refuses:

```
System.NotSupportedException: An attempt was made to load an assembly from a network location
```

**Fixed:** `Unblock-File` now runs automatically on import.

### 3. `mea_integeration.py` vs `from mea_integration import ...`

The filename was misspelled; the import was not. ImportError on startup.

**Fixed:** renamed to `mea_integration.py`.

### 4. `run_single_frame(self, client_socket)` called with no arguments

Leftover from the socket path. TypeError on the first control step.

**Fixed:** parameter removed.

---

## Correctness fixes

### 5. Punishment stimulation could never fire

```python
if np.abs(pole_angle) < 0.262:   # ~15 deg
```

CartPole-v1 terminates at 0.2095 rad (12°), so `|angle|` never reached 0.262 while
an episode was running. The punishment branch was dead code.

**Fixed:** threshold lowered to 0.15 rad (~8.6°), matching the Brian2 simulator,
where this same bug was found and fixed earlier but never ported over.

### 6. Spike detection ran at the wrong sampling rate

```python
time_array = np.linspace(0, 1, raw_neural_data.shape[1])
```

This told `MADs()` the buffer spanned 1 second. It spans 2500 samples / 50 kHz =
**50 ms**. Every filter cutoff was off by about 20×.

**Fixed:** `np.linspace(0, n / self.samplerate, n)`.

### 7. Ties always went right

```python
action = 0 if left_spike_count > right_spike_count else 1
```

At low spike counts ties are common, and every one pushed right. That biases the
agent toward one direction whenever the readout is ambiguous.

**Fixed:** ties now break randomly.

---

## Performance fixes

### 8. Bulk copy instead of per-element marshalling

`handle_data_event` did `np.array(list(net_array))` per channel, which marshals
element by element across pythonnet. Measured:

| Method | Per channel | × 60 channels |
|---|---|---|
| `list()` (old) | 0.99 ms | **59.5 ms** |
| `Marshal.Copy` (new) | 0.13 ms | **7.6 ms** |

The callback budget is 100 ms (threshold 5000 frames at 50 kHz). The old version
fit, but used ~59% of the budget before any other work. **7.8× faster now.**

### 9. Removed a hardcoded 50 ms sleep

`run_cartpole.py` slept 50 ms every control step with no stated purpose. If it was
guarding against something, put it back with a comment saying what.

### 10. `import gym` → `import gymnasium as gym`

The code unpacks a 5-tuple from `step()` and a 2-tuple from `reset()`, which is
the Gymnasium API. Old `gym` returns 4-tuples.

---

## Still open

- **Stimulation amplitude is unverified.** `send_stimulation` now converts
  microvolts to DAC steps using the device's reported resolution and clamps to its
  reported range, which is safe. But `generate_stim_wave` produces ~150 µV peaks,
  which may be far too small to drive a culture. Run once and read the printed
  range before adjusting `stim_gain`.
- **Blanking is still not configured.** We stimulate and record on the same
  electrodes. The MEA2100 has a hardware blanking circuit; nothing in the code
  enables it. Artifact is currently being fed into spike detection.
- **`buffer_size` (50 ms) is half what the callback delivers (100 ms).** Half of
  every recording window is discarded. Left as-is because changing it alters the
  decode window; decide deliberately.
- **Round-trip latency is unmeasured.** See the `latency-*` branches.
