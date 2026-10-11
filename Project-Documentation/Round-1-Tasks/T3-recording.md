# Role 3: Recording

| Owner | Hours | Test days | Works in |
|---|---|---|---|
| Open | 9 | Present at both (runs checks 1 and 3) | `Baseline-Protocol/Hardware/recording.py` (after Kai's Monday split) |

**What this role is about:** getting data *out* of the MEA, completely and accurately. Every sample arrives, in microvolts, and we know
exactly which samples came right after each stimulation pulse. It's careful, detail-oriented work with a hardware library.

**Before writing any call into the MCS library,** look up its real signature in `Project-Documentation/Evidence/McsUsbNet-API-reference.md`.
A wrong call only fails on test day.

**Testing on a laptop:** the library can't load on a Mac. `Evidence/offline_checks.py` shows how to replace the Windows-only modules with
stand-ins (`unittest.mock`), so you can import `recording.py` and feed it fake data. Role 6's fake device arrives Wednesday.

| Due | What |
|---|---|
| Fri Oct 16 | Fixes 1–4, fix 5 part 1, both check scripts; pull request open |
| Sun Oct 18 | Test day 1: checks 1 and 3; make sure recordings reach the shared drive |
| Fri Oct 23 | Fix 5 part 2, plus your test-day fix list |
| Sun Oct 25 | Test day 2 |

---

## Fix 1: Recording setup crashes (P1) · due Fri Oct 16 · about 30 min

**The bug.** `_setup_recording` calls a library function that Python can't use:
```python
block = self.dacq.ChannelBlock
block.Init(channels_in_block)
block.AddBlocksAndChannels(ChannelBlockTypeNet.MultipleHandlesOneQueues,
                           Array[bool]([True] * n_streams), SAMPLE_RATE,
                           self._frames_per_chunk, SampleSizeNet.SampleSize32Signed,
                           SampleDstSizeNet.SampleDstSize32, 0, 0)
```
According to the DLL, `AddBlocksAndChannels` takes `SampleSize` and `SampleDstSize`, two types that are **internal** to the library, so
outside code can't create them. The code passes the public `SampleSizeNet` / `SampleDstSizeNet` instead. pythonnet picks which .NET
function to call by matching argument types exactly, finds no match, and raises
`TypeError: No method matches given arguments for AddBlocksAndChannels`. Nothing can be recorded, and nothing else can be tested on the
hardware until this is fixed.

**Suggested solution.** Use the public `SetSelectedChannels`, which takes the `...Net` types. MCS's own example uses it, and `Init` isn't
needed:
```python
block = self.dacq.ChannelBlock
block.SetSelectedChannels(n_streams, SAMPLE_RATE, self._frames_per_chunk,     # queue holds 1 s; callback every 20 ms
                          SampleSizeNet.SampleSize32Signed, SampleDstSizeNet.SampleDstSize32,
                          channels_in_block)
block.SetCommonThreshold(self._frames_per_chunk)
block.SetCheckChecksum(checksum_ch, timestamp_ch)
```

**How to test it works.**
- **Laptop:** `python Project-Documentation/Evidence/check_dll_api.py ChannelBlockNet` shows both signatures. A unit test with a stand-in
  `ChannelBlock` (a `MagicMock`) asserts `SetSelectedChannels` was called with `SampleSizeNet.SampleSize32Signed` and that
  `AddBlocksAndChannels` was never called.
- **Test day (check 1):** `connect()` completes; `_on_data` fires about 50 times per second, each with 1,000 frames.

---

## Fix 2: Most of the data streams are never read (P8) · due Fri Oct 16 · about 1 h

**The bug.** Setup turns on every data stream the hardware offers: the 60 electrodes, plus analog inputs, digital in/out, the stimulator's
timing signal and checksums (about 77 in MCS's example). But `_on_data` only ever reads the first 60:
```python
for channel in range(N_CHANNELS):                       # N_CHANNELS = 60
    data, n = dacq.ChannelBlock.ReadFramesI32(channel, 0, self._frames_per_chunk, Int32(0))
```
Each stream has its own 1-second queue. If the library expects every queue to be emptied, the unread ones overflow after about a second,
and you get error messages or recording stops. MCS's example reads every stream. We also *need* one of the unread streams: the timing
signal, for fix 5.

**Suggested solution.** Read every stream in `_on_data`. Keep electrodes 0–59, plus the timing stream at `config.timing_stream_index` (found
on test day, check 3). Read and discard the rest. Print `n_streams` once at startup.

**How to test it works.**
- **Laptop:** with a stand-in `ChannelBlock` that reports 77 streams, assert `ReadFramesI32` is called for all 77 per callback.
- **Test day (check 1):** 5 minutes with no "MEA error" messages; samples received equals 50,000 × seconds elapsed.

---

## Fix 3: Short reads are filled with zeros (P10) · due Fri Oct 16 · about 30 min

**The bug.**
```python
chunk[channel, :n] = to_numpy(data, n)
chunk[channel, n:] = 0
```
If the library returns fewer than 1,000 frames, the rest of the chunk is filled with zeros. The amplifier's raw values don't sit at 0, so
the zeros make a sudden jump, which the spike detector's filter turns into fake spikes. The zeros also insert time that never happened, so
everything after them is shifted relative to the stimulation.

**Suggested solution.** Store only the `n` frames actually returned (in fix 5's buffer), and count short reads in `self.short_reads` so we
notice if it happens.

**How to test it works.**
- **Laptop:** feed one full chunk, then a short one (600 frames). The buffer gains exactly 1,600 samples per channel, there are no zeros, and
  `short_reads == 1`.
- **Test day (check 1):** the short-read count is reported. We expect 0.

---

## Fix 4: Nothing is in microvolts (P11) · due Fri Oct 16 · about 30 min

**The bug.** Everything is raw 32-bit numbers from the analog-to-digital converter. Spike detection works on raw numbers (it uses
relative thresholds), but nothing else can be checked. The manual's quick health check is "about 20 µV peak-to-peak noise on every channel
with the test probe", and we can't compare against that.

**Suggested solution.** The library reports the conversion factor:
```python
status, res, res_unit = self.dacq.GetResolutionPerDigit(0, DacqGroupChannelEnumNet.HeadstageElectrodeGroup, 0, 0)
self.uv_per_count = res * 10 ** (-res_unit) * 1e6      # volts per count → µV per count
```
(pythonnet returns the two `ref` parameters as extra return values. Add `DacqGroupChannelEnumNet` to the imports.) Store data in µV, or store
the factor and convert when handing out windows.

**How to test it works.**
- **Laptop:** with a stand-in returning `(0, 8, 9)` (8 × 10⁻⁹ V), `uv_per_count == 0.008`.
- **Test day (check 1):** the real factor is printed. For a sanity check, 24 bits across ±70 mV is about 0.008 µV per count, but trust the
  library's value. With the test probe in, the noise in µV should roughly match what Multi Channel Experimenter showed during setup.

---

## Fix 5: The listening window isn't lined up with stimulation (P9) · part 1 due Fri Oct 16, part 2 due Fri Oct 23 · about 2 h 30 min

**The bug.** Each game step, the code starts the stimulation, then:
```python
with self._lock:
    self._chunks.clear()
time.sleep(window_ms / 1000)
...
voltages = np.concatenate(self._chunks, axis=1)[:, :needed]      # the first 5,000 samples
```
Data arrives in 20 ms chunks, and each chunk arrives *after* its samples were recorded, plus some USB delay. The first chunk after
`clear()` can therefore hold up to 20 ms of data from before that moment. The analyzed window ends up shifted by a different, unknown amount
every step (0–20 ms plus the USB delay), and the end of the stimulation period gets cut off. That matters for two reasons:
- Neurons respond within about 10–20 ms of a pulse, so whether a response lands inside our window is luck.
- Role 5 needs to know exactly which samples follow a pulse, to ignore stimulation artifacts.

**Suggested solution.**
- **Part 1 (week 1):** replace the chunk list with a **ring buffer** holding the last ~2 s of every kept stream, plus a running count of
  samples received (`samples_received`). Add `get_window(start_sample, n_samples)`, which returns exactly those samples (or waits until
  they've arrived).
- **Part 2 (week 2, using the test-day data):** use the timing stream found in check 3 to implement `pulse_samples(since_sample)`, the sample
  numbers where pulses started. Then rewrite `read_spike_counts` to:
  1. find the first pulse after `SendStart`;
  2. take the 100 ms starting there, plus role 5's margin on each side;
  3. pass both the window and the pulse positions to the detector.

**How to test it works.**
- **Laptop (part 1):** unit tests for the ring buffer: samples come out in order; wrap-around past the 2 s end works; asking for samples that
  haven't arrived yet waits, and times out after 2 s.
- **Laptop (part 2):** replay the test-day recording through role 6's replay mode. The first pulse sits at the same offset in every window.
- **Test day 2:** over 100 consecutive windows, the first pulse's position is identical (±1 sample).

---

## Test-day check scripts · due Fri Oct 16 · about 1 h 30 min

Agree the details with role 4; check 3 uses both your code and theirs.

| Script | Does | Passes when |
|---|---|---|
| `hw_check_recording.py` (check 1) | Connects; prints the number of streams; counts callbacks per second over 30 s; counts short reads and compares samples received with 50,000 × seconds over 5 min; prints µV per count; saves **3 minutes of raw data from every stream** (`.npy`) plus a small JSON (date, `HEADSTAGE`, µV per count, number of streams) | No errors; ~50 callbacks/s; 0 short reads; sample count matches |
| `find_timing_stream.py` (check 3) | Records every stream while role 4's code fires pulse trains. For each non-electrode stream, reports whether its values change right after each pulse train starts. | One stream changes at every pulse train and nowhere else. Its index goes into `config.py` and `System-Overview.md`. |

## Done when
- Check 1 passes on test day 2.
- The timing stream index is recorded.
- Windows line up with pulses (part 2 test).
- Your unit tests pass.
