# Latency test — pythonnet path

## Why this branch exists

We don't know how long one closed-loop cycle actually takes on our MEA2100-Mini-60.
That number decides whether plasticity-based feedback can work at all: our STDP
traces decay with τ ≈ 20 ms, so feedback arriving 150 ms after the activity that
caused it has nothing left to attach to.

This branch measures it on the **current** code path — Python calling
`McsUsbNet.dll` through pythonnet.

There is a matching `latency-csharp` branch that measures the same things with no
Python in the loop. Comparing the two tells us whether the pythonnet boundary is
the bottleneck, or whether the delay is hardware/driver-bound and we need to look
at the IFB-C onboard processor instead.

## Running

```bat
python latency_test.py                     :: marshalling bench, NO hardware needed
python latency_test.py --hardware          :: + record-only timing
python latency_test.py --hardware --stim   :: + round-trip latency  (SALINE ONLY)
```

Writes `latency_pythonnet.csv`.

## What it measures

| Metric | Hardware needed | Why |
|---|---|---|
| Marshalling cost | no | Is moving data across pythonnet the bottleneck? |
| Callback duration | yes | If longer than the callback interval, the ring buffer overruns and data is lost silently |
| Callback interval | yes | Should be `threshold / samplerate` = 100 ms |
| Buffer staleness | yes | How often two consecutive reads return identical data |
| Decode time | yes | `MADs()` + `count_spikes()` |
| **Round-trip** | yes | Stim issued → artifact visible in the recording. The real number. |

## Results so far (no hardware)

Cost of moving one channel's ~5000 frames from .NET into numpy:

| Method | Per channel | × 60 channels |
|---|---|---|
| `list()` — what `mea_integeration.py` does now | 0.99 ms | **59.5 ms** |
| `np.fromiter` | 0.82 ms | 49.2 ms |
| `Marshal.Copy` (bulk) | 0.13 ms | **7.6 ms** |

Callback budget is 100 ms. The current approach fits, but uses ~59% of the budget
before any other work happens. `Marshal.Copy` is a 7.8× speedup and is a one-line
change.

## Note on the DLL

`McsUsbNet.dll` was downloaded and lives under OneDrive, so Windows marks it and
.NET refuses to load it:

```
System.NotSupportedException: An attempt was made to load an assembly from a network location
```

This script runs `Unblock-File` automatically. If you hit it elsewhere:

```powershell
Unblock-File -Path "...\Hardware-Pythonnet-Path\McsUsbNet.dll"
```

## Reading the result

| Round-trip | STDP trace remaining |
|---|---|
| 20 ms | 37% |
| 50 ms | 8% |
| 100 ms | 0.7% |
| 150 ms | 0.05% |

Above roughly 50 ms, pair-STDP — the only mechanism our protocol invokes — can no
longer attribute feedback to the activity that produced the action.
