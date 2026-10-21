# Saline benchmark - /tmp/claude-0/demo

**FAKE DATA (dry run, simulated device) - code check only.**

**Finding:** R1 Normal stim: SALPA, SpikeInterface; R2 Current-mode: SALPA, Simple blanking, Template subtraction, SpikeInterface; R3 Short stim: SALPA, Simple blanking, Template subtraction, SpikeInterface; R4 Hardware blanking OFF: no remover passed; R5 Moved decoder zones: SALPA, Simple blanking, Template subtraction, SpikeInterface

Table 1. Verdict per cell (PASS / CHECK / FAIL)

| Condition | No cleaning | SALPA | Simple blanking | Template subtraction | SpikeInterface |
|---|---|---|---|---|---|
| R1 Normal stim | FAIL (decoder biased, false spikes) | PASS | FAIL (decoder biased) | CHECK (false spikes) | PASS |
| R2 Current-mode | FAIL (decoder biased, false spikes) | PASS | PASS | PASS | PASS |
| R3 Short stim | FAIL (decoder biased, false spikes) | PASS | PASS | PASS | PASS |
| R4 Hardware blanking OFF | FAIL (false spikes, long blind period) | FAIL (loses spikes, false spikes, long blind period) | CHECK (false spikes) | CHECK (false spikes) | CHECK (false spikes) |
| R5 Moved decoder zones | FAIL (decoder biased) | PASS | PASS | PASS | PASS |

Table 2. Blind period on STIMULATED electrodes (median ms) - lower is better

| Condition | No cleaning | SALPA | Simple blanking | Template subtraction | SpikeInterface |
|---|---|---|---|---|---|
| R1 Normal stim | 3.2 | 1.7 | 3.2 | 0.0 | 3.0 |
| R2 Current-mode | 1.7 | 1.6 | 3.0 | 0.0 | 3.0 |
| R3 Short stim | 1.5 | 1.4 | 3.0 | 0.0 | 3.0 |
| R4 Hardware blanking OFF | 5.4 | 7.8 | 4.4 | 1.0 | 4.2 |
| R5 Moved decoder zones | 1.7 | 1.4 | 3.0 | 0.0 | 3.0 |

Table 3. Blind period on OTHER electrodes (median ms) - lower is better

| Condition | No cleaning | SALPA | Simple blanking | Template subtraction | SpikeInterface |
|---|---|---|---|---|---|
| R1 Normal stim | 1.5 | 1.6 | 3.0 | 0.0 | 3.0 |
| R2 Current-mode | 0.0 | 1.6 | 3.0 | 0.0 | 3.0 |
| R3 Short stim | 0.0 | 1.4 | 3.0 | 0.0 | 3.0 |
| R4 Hardware blanking OFF | 2.1 | 26.8 | 3.0 | 0.0 | 3.0 |
| R5 Moved decoder zones | 0.0 | 1.2 | 3.0 | 0.0 | 3.0 |

Table 4. False spikes per 100 pulses per channel (other electrodes) - ~0 is right

| Condition | No cleaning | SALPA | Simple blanking | Template subtraction | SpikeInterface |
|---|---|---|---|---|---|
| R1 Normal stim | 63.2 | -0.0 | 0.4 | 7.6 | 0.1 |
| R2 Current-mode | 10.7 | -0.0 | -0.1 | 1.2 | -0.1 |
| R3 Short stim | 11.7 | -0.1 | -0.1 | 2.6 | -0.0 |
| R4 Hardware blanking OFF | 86.7 | 21.3 | 18.8 | 38.3 | 11.8 |
| R5 Moved decoder zones | 4.8 | 0.1 | -0.0 | 1.0 | -0.0 |

Table 5. Injected spikes recovered 2-10 ms after a pulse (other electrodes, %) - higher is better

| Condition | No cleaning | SALPA | Simple blanking | Template subtraction | SpikeInterface |
|---|---|---|---|---|---|
| R1 Normal stim | 100% | 100% | 88% | 100% | 86% |
| R2 Current-mode | 100% | 100% | 89% | 100% | 88% |
| R3 Short stim | 100% | 100% | 89% | 100% | 87% |
| R4 Hardware blanking OFF | 96% | 62% | 90% | 97% | 89% |
| R5 Moved decoder zones | 100% | 100% | 89% | 100% | 87% |

Table 6. Injected spikes recovered 2-10 ms after a pulse (stimulated electrodes, %)

| Condition | No cleaning | SALPA | Simple blanking | Template subtraction | SpikeInterface |
|---|---|---|---|---|---|
| R1 Normal stim | 97% | 100% | 90% | 100% | 89% |
| R2 Current-mode | 100% | 100% | 90% | 100% | 88% |
| R3 Short stim | 100% | 100% | 90% | 100% | 88% |
| R4 Hardware blanking OFF | 79% | 34% | 86% | 89% | 87% |
| R5 Moved decoder zones | 100% | 100% | 95% | 100% | 95% |

Table 7. Game decoder picks the STIMULATED side (%) - 50% is right on saline (decoder ignores blanked samples)

| Condition | No cleaning | SALPA | Simple blanking | Template subtraction | SpikeInterface |
|---|---|---|---|---|---|
| R1 Normal stim | 100% | 41% | 100% | 41% | 48% |
| R2 Current-mode | 100% | 50% | 51% | 56% | 53% |
| R3 Short stim | 100% | 58% | 62% | 62% | 64% |
| R4 Hardware blanking OFF | 44% | 62% | 59% | 50% | 59% |
| R5 Moved decoder zones | 77% | 62% | 59% | 52% | 61% |

Table 8. Same, with today's count_spikes unchanged (counts blanked samples too)

| Condition | No cleaning | SALPA | Simple blanking | Template subtraction | SpikeInterface |
|---|---|---|---|---|---|
| R1 Normal stim | 100% | 41% | 100% | 41% | 32% |
| R2 Current-mode | 100% | 51% | 54% | 56% | 49% |
| R3 Short stim | 100% | 58% | 62% | 62% | 65% |
| R4 Hardware blanking OFF | 44% | 62% | 59% | 50% | 59% |
| R5 Moved decoder zones | 77% | 62% | 59% | 52% | 55% |

