# Pipeline Review: Baseline-Protocol/Hardware

Every problem found in the Python hardware pipeline (`Baseline-Protocol/Hardware/`), checked against the
MEA2100-Mini manual, the McsUsbNet.dll metadata, offline tests, and the DishBrain and UCSC organoid papers.

Each problem says where it is, what the code does, why that's a problem, what you would see on the
hardware, how to fix it, and how to prove the fix worked. Task docs in `Round-1-Tasks/` link back here by problem number.

Line numbers refer to `mea_device.py` as it was before the round-1 split into `recording.py`, `stimulation.py` and
`spike_detection.py` (commit `dfb6cd4`). After the split, find the same function by name.

**How each finding was checked**

| Label | Meaning |
|---|---|
| Confirmed (DLL) | Read from McsUsbNet.dll's own metadata with `Evidence/check_dll_api.py`. Not a guess. |
| Confirmed (offline) | Reproduced with `Evidence/offline_checks.py` on a laptop. |
| Manual | Stated in `References/MCS_MEA2100-Mini-System-manual.pdf` (page given). |
| Code reading | Follows from reading the code; needs a hardware test to see how big the effect is. |
| Literature | DishBrain (Kagan et al., 2022) or the UCSC organoid CartPole paper (Robbins et al., *Cell Reports*, 2026). |

**When it must be fixed**

- **Before hardware tests**: the first run on the hardware fails or gives meaningless data without it.
- **Before cells**: hardware tests can run, but a live culture should not see the system until this is fixed or measured.
- **Round 2**: matters for real experiments, not for proving the pipeline works.

---

## A. Startup: blocks the first run

### P1. Recording setup calls a function Python cannot use
**Confirmed (DLL). Before hardware tests. Blocks everything else.**

**Where:** [`mea_device.py` lines 117–124](../Baseline-Protocol/Hardware/mea_device.py#L117-L124), inside `_setup_recording()`.

**What the code does:**
```python
block = self.dacq.ChannelBlock
block.Init(channels_in_block)
block.AddBlocksAndChannels(ChannelBlockTypeNet.MultipleHandlesOneQueues,
                           Array[bool]([True] * n_streams), SAMPLE_RATE,
                           self._frames_per_chunk, SampleSizeNet.SampleSize32Signed,
                           SampleDstSizeNet.SampleDstSize32, 0, 0)
```

**Why it's wrong:** `AddBlocksAndChannels` exists, but its fifth and sixth parameters are of types `SampleSize` and
`SampleDstSize`. Those two types are marked *internal* in the DLL: code outside the DLL can't create them. The code passes
`SampleSizeNet` and `SampleDstSizeNet` instead, which are different (public) types. pythonnet chooses which .NET method to call by
matching argument types exactly, so it finds no match.

From the DLL metadata:
```
int  AddBlocksAndChannels(ChannelBlockTypeNet type, bool[] selectedChannels, int queuesize, int threshold,
                          SampleSize samplesize, SampleDstSize sampleDstSize, int nByteOffset, int nChannelOffset)
void SetSelectedChannels (int nChannels, int queuesize, int threshold,
                          SampleSizeNet samplesize, SampleDstSizeNet sampleDstSize, int ChannelsInBlock)
- SampleSize    (INTERNAL)
- SampleDstSize (INTERNAL)
```

**What you'd see:** `connect()` raises `TypeError: No method matches given arguments for AddBlocksAndChannels`.
By then the recording side and the stimulator are already connected, and nothing releases them (see P3).

**Fix:** use the public `SetSelectedChannels`, which takes the `...Net` types. MCS's own example code and earlier
versions of our recording code used this call, and `Init` isn't needed with it:
```python
block = self.dacq.ChannelBlock
block.SetSelectedChannels(n_streams, SAMPLE_RATE, self._frames_per_chunk,   # queue = 1 s, callback every 20 ms
                          SampleSizeNet.SampleSize32Signed, SampleDstSizeNet.SampleDstSize32,
                          channels_in_block)
block.SetCommonThreshold(self._frames_per_chunk)
block.SetCheckChecksum(checksum_ch, timestamp_ch)
```

**Proof it's fixed (test day, check 1):** `connect()` completes; `_on_data` is called about 50 times per second (count calls over 10 s,
expect ~500); every call returns 1,000 frames per channel; no "MEA error" lines print.

---

### P2. The stimulator connection is never checked
**Confirmed (DLL) for the return value; behavior needs a hardware check. Before hardware tests.**

**Where:** [`mea_device.py` line 93](../Baseline-Protocol/Hardware/mea_device.py#L93).

**What the code does:** `self.stg.Connect(entry)` and moves on.

**Why it's wrong:** `Connect` returns a status code (`uint`; 0 means success), the same way `dacq.Connect` does two lines
earlier, where the code *does* check it. The device is opened twice (once for recording, once for the stimulator). If the second open
fails, for example because the first one holds a lock, every later stimulator call fails or does nothing. MCS's example code passes a lock
mask as a second argument (`Connect(entry, 1)`); the DLL has both versions:
```
uint Connect(CMcsUsbListEntryNet entry, uint LockMask)
uint Connect(CMcsUsbListEntryNet entry)
```

**What you'd see:** recording works, the game runs, and there is no stimulation at all. Episode lengths look like coin flips
(about 22 steps), so nothing looks obviously broken.

**Fix:**
```python
status = self.stg.Connect(entry)
if status != 0:
    raise RuntimeError(f"Could not connect to the stimulator (status {status})")
```
If it fails on the hardware, try `Connect(entry, 1)` to match the MCS example.

**Proof it's fixed:** status 0 on the hardware, and stimulation shows up as artifacts in the recording (see P4 and P14).

---

### P3. A crash during setup leaves the MEA locked; shutdown never stops the stimulator
**Code reading. Before hardware tests.**

**Where:** [`run_hardware.py` line 28](../Baseline-Protocol/Hardware/run_hardware.py#L28) and
[`mea_device.py` lines 221–227](../Baseline-Protocol/Hardware/mea_device.py#L221-L227).

**What the code does:** `mea.connect()` runs *before* the `try:` block, so the `finally: mea.close()` cleanup only covers
errors that happen after setup has fully finished. `close()` stops recording and disconnects, but never tells the stimulator to stop.

**Why it matters:** during the first hardware tests, setup is exactly where errors will happen (P1 guarantees one). Each time,
the device stays opened by a dead Python process. The next run then fails to connect until someone power-cycles the interface
board, and the manual recommends switching the system off before reconnecting headstages anyway (p. 7). Separately, a pulse train
already uploaded and started will finish playing even after Python exits.

**Fix:**
```python
mea = MEADevice()
try:
    mea.connect()
    ...                      # episodes
finally:
    mea.close()

def close(self):
    if self.stg is not None:
        self.stg.SendStop(1)          # stop trigger 1, the one SendStart(1) uses
        self.stg.Disconnect()
    if self.dacq is not None:
        self.dacq.StopDacq(0)
        self.dacq.Disconnect()
```
`close()` must also work on a half-connected device (only `dacq` set, `stg` still `None`), which the checks above handle.

**Proof it's fixed:** break `connect()` on purpose (for example, set a wrong headstage), run it twice in a row: the second run must
get as far as the first, without power-cycling anything.

---

## B. Stimulation

### P4. Only the left stimulus generator is switched to voltage mode
**Confirmed (DLL) for the signature; the effect needs a hardware check. Before cells.**

**Where:** [`mea_device.py` line 134](../Baseline-Protocol/Hardware/mea_device.py#L134).

**What the code does:** `self.stg.SetVoltageMode(0)`.

**Why it's wrong:** the DLL has two versions:
```
void SetVoltageMode()               # all stimulator channels
void SetVoltageMode(uint channel)   # one channel
```
Passing `0` selects the one-channel version, for channel 0. The code sends the left pulse train to stimulator channel
`2*HEADSTAGE + 0` and the right to `2*HEADSTAGE + 1` (lines 207–208). With `HEADSTAGE = 0`, the right generator (channel 1) is never
set to voltage mode. With any other `HEADSTAGE`, neither generator is. The manual confirms each generator can run in current *or*
voltage mode (p. 7; specs p. 21: ±1 mA current or ±10 V voltage).

**What you'd see:** whatever mode the right generator happens to be in stays in effect. If it's current mode, the same number
(75,000) is read as a current instead of a voltage. That makes left and right stimulation physically different, and the decoder
compares left against right, so it biases the action directly. On the test probe (220 kΩ per electrode), a current-mode pulse
that large would run into the ±16 V compliance limit and produce a far larger artifact on one side.

**Fix:** `self.stg.SetVoltageMode()` (no argument). Also check whether `SetVoltageMode` must run before the electrode setup;
MCS's example calls it just before `PrepareAndSendData`, which is where it is now.

**Proof it's fixed:** on the test probe, stimulate left only, then right only, with the same settings. Average the artifact
around each pulse on the stimulated electrodes. The two sides should match in size and shape (within a few percent).

---

### P5. `HEADSTAGE`: what it means, and the timing stream
**Partly resolved by the manual. Before hardware tests (it's a setting to get right).**

**Where:** [`mea_device.py` line 32](../Baseline-Protocol/Hardware/mea_device.py#L32), used in `_setup_stimulation` and `_send`.

**What the manual settles:** the headstage plugs into the Signal Collector Unit (SCU), which has four inputs labelled
**HS1–HS4** (p. 7, p. 21). `HEADSTAGE` is that input's number minus one (HS1 = 0 … HS4 = 3). The DLL agrees: the stimulator methods
name this parameter `Scu_HS`. MCS's example code uses `HeadStage = 3`, meaning that example's
headstage was on HS4. So the default of 0 is only right if your headstage is plugged into HS1.

**What's still open:**
1. The recording side never uses `HEADSTAGE`. `SetNumberOfAnalogChannels(60, 0, 0, 8, 0)` asks for 60 channels on "HS1", and MCS's
   example says that for the Mini "it is assumed that only one HS is connected". So recording probably picks up whichever single
   headstage is connected, wherever it's plugged in. Keep exactly one headstage plugged into the SCU.
2. The *timing stream* (P9 needs it) is enabled with `Hs1SidebandLow | Hs1SidebandHigh`. The DLL only has these flags for Hs1 and Hs2
   (`DigitalDatastreamEnableEnumNet`), while the SCU has four ports. MCS's example reads the timing stream at data stream
   `69 + HeadStage`. Which stream carries it on our setup has to be found on the hardware.

**Fix:** look at the SCU, set `HEADSTAGE` to match, and write the port into the session log (P17). Record which data stream
changes when the stimulator fires (test day, check 3, by roles 3 and 4).

**Proof it's fixed:** stimulation artifacts appear on the expected electrodes (see P15); the timing stream index is written down
in `System-Overview.md`.

---

### P6. The amplifier protection switch is turned off on every electrode
**Needs MCS support or a hardware comparison. Before cells.**

**Where:** [`mea_device.py` line 132](../Baseline-Protocol/Hardware/mea_device.py#L132).

**What the code does:** `SetEnableAmplifierProtectionSwitch(HEADSTAGE, electrode, False)` for all 60 electrodes.

**Why it's a question:** the manual doesn't describe this switch. MCS's example code
sets it to `True`. The baseline sets it to `False` with no comment. From its name, it protects the recording amplifier input while
stimulating. Turning it off could make artifacts larger, saturate amplifiers, or worse. We have no evidence either way.

**Fix:** match MCS's example (`True`) unless MCS support (support@multichannelsystems.com, manual p. 20) says otherwise. If the baseline
author had a reason for `False`, write it in a code comment.

**Proof it's settled:** a written answer from MCS, or a hardware comparison of artifact size and recovery time with the switch on
and off, saved in `System-Overview.md`.

---

### P7. Stimulation settings need a sign-off, and they differ from DishBrain in ways worth knowing
**Mostly OK, checked against the manual. Before cells (sign-off).**

**Where:** [`mea_device.py` lines 38–40](../Baseline-Protocol/Hardware/mea_device.py#L38-L40) and `_setup_stimulation`.

**What checks out:**
- 75 mV is well inside the generators' ±10 V voltage range (manual p. 21).
- Every segment duration the code produces (200 µs phases, the gaps, random onsets) is a multiple of the stimulator's 20 µs time
  resolution (manual p. 21; verified for 2,000 random pulse trains in `offline_checks.py`).
- The pulse trains add up to exactly 100 ms and alternate positive then negative (biphasic, charge balanced).

**What differs from DishBrain (Kagan et al., STAR Methods):**

| | DishBrain | Our baseline |
|---|---|---|
| Electrodes stimulated | 8 "sensory" electrodes, separate from the electrodes that decide the action | all 30 electrodes on one half at once, and the same electrodes then decide the action |
| Sensory input | 75 mV, 4–40 Hz depending on ball distance, on one of 8 sites by ball position | 75 mV, always 2 pulses per 100 ms (20 Hz), on the side the pole leans |
| After a hit | 75 mV at 100 Hz for 100 ms, all 8 electrodes | nothing special |
| After a miss | 150 mV at 5 Hz, random sites, 4 s, then 4 s pause | nothing; next episode starts immediately |

The UCSC organoid study used 200 µs per phase like ours, but on a different chip (MaxOne HD-MEA, much smaller platinum electrodes),
so their amplitude numbers don't carry over to our TiN electrodes.

**Fix:** none needed for the pipeline. The lab lead should sign off on 75 mV / 200 µs / 30 electrodes before cells, and the
first cell session should include a stimulation check (P18) to confirm these settings actually make neurons fire.

---

## C. Recording and timing

### P8. Most of the recorded data streams are never read
**Code reading. Needs a hardware check. Before hardware tests.**

**Where:** [`mea_device.py` lines 139–147](../Baseline-Protocol/Hardware/mea_device.py#L139-L147).

**What the code does:** recording is set up for every data stream in the block (`n_streams = channels_in_block // 2`). Besides the 60
electrodes, that includes the interface board's analog inputs, digital in/out, the stimulator timing stream, and checksum streams.
Going by the comments in MCS's example, there are about 77 in total. `_on_data` reads only streams 0–59.

**Why it might matter:** each stream has its own queue (1 s long). If the library expects every queue to be emptied, the unread ones
fill up after about a second and the library either reports an overflow or stops sending data. MCS's example reads *every* stream in
the callback. We also need one of the unread streams, the timing stream, for P9.

**What you'd see:** recording works for about a second, then "MEA error: …overflow…" messages, or `read_spike_counts` raises
"No data from the MEA for 2 s."

**Fix:** in `_on_data`, read every stream. Keep electrodes 0–59 and the timing stream, and discard the rest.

**Proof it's fixed:** a 10-minute recording on the test probe with no error messages, and the received sample count matches
50,000 × elapsed seconds.

---

### P9. The listening window isn't lined up with the stimulation
**Code reading. Before cells.**

**Where:** [`mea_device.py` lines 149–162](../Baseline-Protocol/Hardware/mea_device.py#L149-L162) (`read_spike_counts`), called right
after `_send` → `SendStart` in `run_hardware.py`.

**What the code does:**
1. `stimulate_*()` uploads the pulse trains and calls `SendStart`. The stimulator starts playing.
2. `read_spike_counts(100)` empties the chunk list, sleeps 100 ms, waits until at least 5,000 samples have arrived, and keeps the
   **first** 5,000.

**Why it's a problem:** the library delivers data in 20 ms chunks (1,000 samples), and each chunk arrives *after* its samples were
recorded, plus some USB delay. The first chunk after the list is emptied therefore holds up to 20 ms of data from before that moment.
The window actually analyzed is shifted earlier than intended by an amount that changes every step (0–20 ms plus an unmeasured USB
delay). The last part of the stimulation period gets thrown away.

This matters because:
- Evoked responses in cultures come within about 10–20 ms of a pulse (UCSC counted "first-order" responses in a 10 ms window). Whether
  a given response lands inside our window is currently a matter of luck.
- Hiding stimulation artifacts (P14) means knowing *exactly* which samples follow a pulse. Right now we don't.
- Per-step jitter makes the spike counts noisier, which makes decisions noisier.

**Fix:** use the stimulator's timing stream. The `CreateSideband` call in `_send` generates the bits that switch the electrodes and
blanking during each pulse, and `_setup_recording` already enables the HS1 sideband streams (`Hs1SidebandLow/High`). MCS's example
plots one of these streams next to the electrode data, which suggests it records the stimulator state for every sample (confirm on
the hardware). With it, the pulse times appear in the same sample clock as the electrode data:
1. Keep a running sample counter in `_on_data`, and keep the last ~1 s of data in a ring buffer instead of a list that gets emptied.
2. After `SendStart`, wait until the timing stream shows the first pulse, then take exactly the 100 ms from that sample onward.
3. Hand the pulse sample positions to the spike detector so it can ignore them (P14).

**Proof it's fixed:** on the test probe, the artifact of the first pulse lands at the same sample offset (±1 sample) in 100
consecutive windows.

---

### P10. Short reads are filled with zeros
**Code reading. Before cells (small).**

**Where:** [`mea_device.py` line 145](../Baseline-Protocol/Hardware/mea_device.py#L145): `chunk[channel, n:] = 0`.

**Why it's a problem:** if the library ever returns fewer frames than asked for, the rest of the chunk is filled with zeros. Raw values
from a DC-coupled amplifier (bandwidth starts at DC, manual p. 21) sit at some offset, not at 0. The zero block becomes a sudden jump,
and after band-pass filtering a jump looks like a spike. It also inserts fake time: data from later chunks shifts relative to the
stimulus.

**Fix:** only keep the `n` frames actually returned, and count how often `n` is short. If it happens more than rarely, that points to
P8.

---

### P11. Raw readings are never converted to microvolts
**Confirmed (DLL) that the conversion exists. Before cells.**

**Why it matters:** spike counting uses relative thresholds (multiples of each electrode's noise), so it works on raw numbers. But
noise checks, logs and analysis need real units. The manual gives a concrete check: the test probe should show **about 20 µV
peak-to-peak noise** on every channel (p. 11). We can't compare against that without converting.

**Fix:** `GetResolutionPerDigit` exists in the DLL:
```
uint GetResolutionPerDigit(uint virtualDevice, DacqGroupChannelEnumNet group, ref int res, ref int resUnit)
```
Call it once in `_setup_recording` with `DacqGroupChannelEnumNet.HeadstageElectrodeGroup`, the same way MCS's example does
(`resolution = res * 10**(-resUnit)` volts per count), and multiply raw counts by it before logging. (For reference: 24 bits over
±70 mV is about 8 nV per count; use the value the DLL reports, not this estimate.)

**Proof it's fixed:** our Python noise numbers on the test probe match what Multi Channel Experimenter shows on the same probe.

---

### P12. The headstage's hardware filter settings are unknown
**Manual. Before hardware tests (write it down).**

The headstage has its own high-pass and low-pass filter (Bessel type) before the data reaches Python. It's set with the MCS Filter
Configuration program and stored on the device, so a previous user may have changed it (manual pp. 15–16). Our spike detector
band-passes 300–3000 Hz. If the hardware low-pass sits below 3 kHz, or the high-pass is unusually high, we'd silently lose part of the
spike band.

**Fix:** open MCS Filter Configuration, write down the current settings in `System-Overview.md`, and add them to the session log. Don't
change them without telling the team.

---

## D. Spike detection and decoding

### P13. The spike detector invents spikes at the edges of every window
**Confirmed (offline). Before cells.**

**Where:** [`mea_device.py` lines 45–59](../Baseline-Protocol/Hardware/mea_device.py#L45-L59) (`count_spikes`).

**What the code does:** for each 100 ms window on its own: band-pass 300–3000 Hz with `sosfiltfilt`, estimate each electrode's noise
as `median(|signal|) / 0.6745`, and count downward crossings of −5 × noise.

**What's right:** the method itself is standard and works. With 133 spikes planted in noise it reported 138 (a few counted twice),
and 54 of 60 electrodes were counted exactly.

**What's wrong:** filtering a short window separately makes the filter "start up" at each end, and that start-up creates swings that
cross the threshold. On pure noise with no spikes at all:

| | Value |
|---|---|
| False spikes per electrode per 100 ms window | 0.15 (about 1.5 fake spikes per second per electrode) |
| Share of those within 2 ms of a window edge | 100% |
| What Gaussian noise alone should give at −5σ | about 0.0014 per window |
| Real spikes expected from a culture firing at 1–5 Hz | 0.1–0.5 per electrode per window |

So the fake rate is about the same size as a real culture's resting rate. Fake spikes hit both halves equally, so they don't push
decisions to one side, but they swamp real differences and make decisions closer to coin flips.

**Fix (recommended, tested):** **add a margin and trim it.** Filter the window plus 10 ms on each side, then count only the middle
100 ms. On pure noise this cut false spikes from 0.144 to 0.0004 per electrode per window. It needs the ring buffer from P9 to fetch
the extra 10 ms. (Alternative: keep the filter running continuously across chunks with `scipy.signal.sosfilt` and saved state `zi`, as
DishBrain does. That only works if every chunk is fed through in order, which the game loop doesn't currently do.)

Also add:
- **A refractory period** (about 1 ms): ignore a second crossing within 1 ms on the same electrode, so one spike isn't counted twice.
- **A fixed noise level per session**, measured from a spontaneous recording at the start, instead of re-estimating every 100 ms.
  Otherwise bursts of real activity raise their own threshold.

**Proof it's fixed:** role 5's pure-noise unit test reports ≤ 0.01 false spikes per electrode per window; on a real test-probe
recording, fewer than 1 spike per electrode per minute.

---

### P14. Stimulation artifacts can be counted as spikes, and they push the cart the "right" way
**Code reading plus literature. Must be measured on the hardware. Before cells. This is the most important check before cells.**

**Why it's likely:** the stimulated half is also the half that votes. Blanking disconnects the amplifiers during each pulse plus 40 µs
(`Bit0Time = 40` in `_send`), but the manual only says blanking "reduces stimulus artifacts" (p. 7). Whatever is left after blanking
ends (the electrode settling back, the step where blanking switches off, filter ringing from that step) lands on the stimulated
electrodes, inside the listening window.

**Why it's dangerous:** the predictable stimulus goes to the side the pole leans toward. Extra "spikes" on that side push the cart toward
the lean, and in CartPole that's the correct move. Artifacts alone would therefore produce *good-looking* performance with no neurons
involved:

| What drives the decisions | Average episode length |
|---|---|
| Always pushes one way (stuck) | ≈ 9 steps |
| Coin flip (no usable signal) | ≈ 22 steps |
| Pushes toward the lean 60% of steps | ≈ 30 steps |
| Pushes toward the lean 75% of steps | ≈ 41 steps |
| Pushes toward the lean every step | ≈ 43 steps |

**This has happened before.** DishBrain's own pilot study found that their control chips (no neurons) showed apparent performance.
They traced it to artifacts getting past their first artifact-hiding method, and replaced that method ("consensus blinding") with
"command count blinding", which ignores *all* activity whenever a stimulation command is sent (STAR Methods, "Pilot test with EXP3
algorithm"). The UCSC paper warns that even inanimate hydrogels improved in a Pong setup, and designed its training stimulation so it
"cannot directly influence task performance through immediate artifacts."

**How to measure it (on the hardware):**
1. On the test probe now, and on a saline / media-only MEA (real electrodes, no cells) once we have a spare MEA: stimulate one side at
   a time and average the raw signal around each pulse (needs P9's pulse times). Measure how long until the signal is back within noise. Do this with blanking on, and with
   the protection switch on and off (P6).
2. Run the full closed loop with no cells (test probe now, saline MEA later) for 20+ episodes. **Pass: average ≈ 22 steps and about
   50/50 left/right actions.** Fail: 30+ steps, or actions that follow the stimulated side.

**Fix:** have the spike detector ignore a window after every pulse on all electrodes (DishBrain-style blinding). Its length comes from
step 1, probably a few ms. This loses responses within that window; that's acceptable for round 1. Better artifact removal (SALPA,
used by the UCSC group) is a round-2 option; see `Experiment-Design-Notes.md`.

---

### P15. "Left half" and the electrode numbering haven't been checked
**Manual plus code reading. Needs a hardware check. Before cells.**

**Where:** [`feedback.py` lines 10–11](../Baseline-Protocol/Hardware/feedback.py#L10-L11) (`LEFT_CHANNELS = 0–29`) and the
`electrode` index in `_setup_stimulation`.

**Why it's a problem:**
1. Channels 0–29 are the first 30 *data* channels in amplifier order. Whether those electrodes form the physical left half of the
   array depends on the MEA layout. The manual stresses that MEAs aren't symmetrical: the text on the MEA must face right, and an
   internal reference electrode must sit on the left. Otherwise "the MEA layout will not match with the pin layout of the channel map"
   (p. 13). An MEA put in the wrong way round silently swaps or scrambles the halves.
2. The stimulator's `electrode` index (0–59) may not follow the same numbering as the recording data channels.
3. MEAs with an internal reference electrode use one of the 60 positions for it. That channel records no spikes and shouldn't be
   counted in a half.

**What you'd see:** "left" stimulation lands partly on "right" decoding electrodes, so side-specific responses blur, or the halves
end up different sizes.

**Fix (on the hardware, with the test probe):**
1. Find out which MEA type the lab uses (ask the wet-lab group) and pull its layout from MCS's datasheet, or from the layout view in
   Multi Channel Experimenter.
2. Stimulate one stimulator electrode index at a time and see which recorded channel shows the biggest artifact. This gives a
   stimulator-index → recording-channel table.
3. Write `channel_map.py` with physical-left and physical-right lists for both numberings, excluding reference or ground positions.
   `feedback.py` imports from it.

---

### P16. Uneven activity between the halves will pin the decision to one side
**Literature plus code reading. Measure before cells; the fix is a round-1 option.**

**Where:** [`feedback.py` `choose_action`](../Baseline-Protocol/Hardware/feedback.py#L28-L41).

**Why it's likely:** real cultures are rarely balanced. If the left half fires twice as much at rest, it wins most windows no matter
what the pole does, and the cart is pushed one way: about 9 steps per episode. DishBrain hit exactly this: "asymmetrical spontaneous
spiking activity in cultures would cause the paddle to move swiftly in only one direction." They added a gain that scaled each motor
region toward a 20 Hz target (STAR Methods, "Output configuration").

There is also a counting issue. At 1–5 Hz per electrode, a 100 ms window gives roughly 3–15 spikes per half. Small counts mean
frequent ties (coin flips) and noisy decisions. UCSC used 200–300 ms windows plus smoothing across windows.

**Fix for round 1:** *measure first.* The spontaneous recording at the start of every session (P18) gives each half's resting rate. Log
it. Add an *optional*, off-by-default setting that divides each half's count by its resting rate before comparing. Always log the raw
counts too, because Feldman's homeostasis concerns (see `Experiment-Design-Notes.md`) require seeing raw rates drift.

---

## E. The experiment loop and its data

### P17. Almost nothing is logged
**Code reading. Before hardware tests (the test days need logs).**

**Where:** [`run_hardware.py` line 57](../Baseline-Protocol/Hardware/run_hardware.py#L57): only `episode_lengths.csv`.

**Why it matters:** without step-level logs nobody can tell a stuck decoder from artifacts from a quiet culture, and none of the later
controls (Feldman's dose matching, yoked replay, decoder swap) can be built.

**What to log:**
- **Per session (JSON):** date and time, operator, culture ID and days in vitro (DIV), MEA ID and type, SCU port / `HEADSTAGE`, hardware
  filter settings (P12), the full settings file (`config.py`), git commit hash, µV-per-count (P11), free-text notes.
- **Per step (CSV, one row):** session, episode, step, wall time, first sample number of the listening window, cart position and
  velocity, pole angle and angular velocity, feedback type (predictable or unpredictable), stimulated side, pulse times per generator,
  left count, right count, tie flag, action.
- **Per step (binary, `.npz`):** the 60 per-electrode spike counts.
- **Raw data:** optional. 60 channels × 50 kHz × 4 bytes is **12 MB/s, about 43 GB per hour**. Save raw only for hardware tests and the
  spontaneous / stimulation-check blocks, or save only each step's 100 ms window (about 1.2 MB per step).
- **The stimulation schedule** (when each pulse went where) is already part of the per-step log above. That's exactly what a
  yoked-replay control needs later.

---

### P18. The loop only has one mode, and sessions are counted in episodes
**Code reading plus literature. Before cells.**

Testing on cells needs more than the closed loop. Both papers ran structured sessions:
- **DishBrain:** daily activity scans, 20-minute gameplay sessions analysed in two parts (first 5 min, then 6–20 min), and rest sessions
  where the culture drove the paddle with no stimulation.
- **UCSC:** spontaneous recording first, then a stimulation check (each candidate electrode stimulated 50 times at 2 Hz, responses counted
  in a 10 ms and a 200 ms window), then 15-minute training cycles with 45-minute rests.

Our 20 episodes last about 1–2 minutes.

**Fix:** add modes to `run_hardware.py`, chosen by a setting:
1. **`spontaneous`:** record N minutes with no stimulation; save per-electrode rates and each half's rate.
2. **`stim_check`:** left-only pulses, then right-only, e.g. 50 pulses each at 1 Hz; save per-electrode spike counts 0–10 ms and
   10–200 ms after each pulse, after artifact hiding.
3. **`closed_loop`:** the current loop, stopping after a set *time* (e.g. 15 min) rather than a set number of episodes.

A standard session is then `spontaneous → stim_check → closed_loop → spontaneous`.

---

### P19. The design is a reflex, so a good score doesn't mean learning
**Design note. Round 1 should state this; it doesn't need fixing to validate the pipeline.**

Stimulation goes to the side the pole leans toward, and that same side's spikes vote for the action. Any response to stimulation
(evoked spikes, or artifacts) pushes the cart the correct way, giving roughly 30–43 steps (table in P14) without any learning. DishBrain
deliberately separated its sensory electrodes from its motor regions because this "precludes a direct relationship between input
stimulation and output activity", and noted that the simple left-pushes-left setup "would be most easily influenced by various sources of
bias." UCSC kept input, output and training electrodes separate for the same reason.

**Layout v2** (round 1, role 1) builds the separate input/output layout as an option.

**What round 1 can claim:** "the pipeline runs end to end, and stimulation evokes side-specific responses." That's a real, useful result,
and the right first step. Claims about learning come in round 2, with the controls in `Experiment-Design-Notes.md`.

---

### P20. No failure signal; only the lean side is encoded
**Design note. Round 2.**

- **No consequence for failing:** DishBrain's main teaching signal was unpredictable stimulation after each miss (150 mV, 5 Hz, random
  sites, 4 s, then a 4 s pause). UCSC delivered training stimulation only at the end of episodes, and only when performance was dropping.
  Our next episode starts immediately. Unpredictable stimulation does happen, but only on the ~14% of steps where the pole is already
  past 0.15 rad.
- **Only the lean direction is sent:** not how far it leans or how fast (DishBrain rate-coded 4–40 Hz; UCSC rate-coded angle at
  ~0.8–8.9 Hz on two input sites). The poster describes frequency and amplitude encoding; the baseline doesn't do that yet.

Both are deliberate simplifications in the baseline. Keep them for round 1.

---

## F. Development and setup

### P21. Nobody can work on the hardware code without the Windows computer
**Code reading. Before hardware tests (it decides how many people can work at once).**

`mea_device.py` loads `clr` and the DLL at the top of the file, so it can't be imported on a Mac or a laptop without the hardware.
Five people would be queuing for one Windows computer.

**Fix:** a `FakeMEADevice` with the same five methods (`connect`, `stimulate_predictable`, `stimulate_unpredictable`,
`read_spike_counts`, `close`). It should run in two ways: (a) synthetic spikes plus optional fake artifacts on the stimulated side, and
(b) replaying recordings from the test days. `run_hardware.py` picks real or fake from a setting. `Evidence/offline_checks.py`
already shows how to import `mea_device.py` without the DLL.

---

### P22. The Windows computer's setup isn't written down
**Manual. Before hardware tests.**

The Windows computer connected to the MEA (currently Ryan's laptop) needs the following, from the manual (pp. 10–12) and
the DLL file itself:
- Windows on an Intel/AMD processor. The DLL is 64-bit x86 and contains native Windows code, so it won't load on a Mac or an
  ARM laptop. The manual lists Windows 10 or 8.1, English or German (other system languages "may lead to software errors").
  If you're on Windows 11, check MCS's site for support.
- Install **Multi Channel Suite** even though we use Python: it installs the device driver (p. 10).
- Plug the interface board's USB-C into a **USB 3.0 port directly on the computer**. No hub or dock; on a desktop, avoid front-panel
  ports, which often go through an internal hub (p. 12).
- Power plan "High performance", no standby, screen saver off, be careful with antivirus (p. 10).
- **Only one program can drive the device at a time:** one SCU "is always operated independently by one instance of the software"
  (p. 11). Close Multi Channel Experimenter before running Python, and the other way round.
- `McsUsbNet.dll` is 64-bit .NET Framework 4, so use **64-bit Python** and `pythonnet` 3.x. Pin versions in `requirements.txt`
  (pythonnet 2 and 3 handle arguments differently).
- The **Microsoft Visual C++ 2015–2022 x64 runtime**: the DLL links against it (`MSVCP140.dll`, `VCRUNTIME140.dll`). It's usually
  installed already.
- Mains hum in the US is **60 Hz** (the manual says 50 Hz because it's European). If noise is high, shield with grounded aluminium foil
  (pp. 11, 19).

**Fix:** a `SETUP-WINDOWS.md` with these steps, the exact versions installed, and the "first functional test" from the manual (test
probe in Multi Channel Experimenter, about 20 µV peak-to-peak noise on every channel).

---

### P23. Repository housekeeping
**Code reading. Before hardware tests.**

1. **`Hardware-Pythonnet-Path/` cannot run.** `mea_integeration.py` imports four names that don't exist in the DLL (`CMcsUsbBStimNet`,
   `CreateBStim`, `SetStimulationPattern`, `StartStimulation`), so it fails on import. The root `spike.py` and `square.py` are the old
   versions (the noise-counting spike detector, and the encoder that treats radians as degrees). The root README still calls these the
   "full" version. Move them to `archive/`.
2. **Brian2 is out of scope** for now, but the README tells new members to start with it. Archive it or relabel it.
3. **`McsUsbNet.dll` is committed twice** (identical copies). Keep one.
4. **Access:** the repo is on Ryan's personal account. Everyone needs collaborator access, and `main` should require pull requests.
5. **The MCS manual should not be pushed to a public repo.** Its imprint says no part may be reproduced without MCS's permission.
   It's listed in `.gitignore`; download it from multichannelsystems.com into `Project-Documentation/References/`. The two papers are
   open access (CC BY).
