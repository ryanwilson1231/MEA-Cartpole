# Latency test — native C# path

## Why this branch exists

The control group for the `latency-pythonnet` branch.

Our current hardware path is Python → pythonnet → `McsUsbNet.dll` → USB. Every
loop iteration crosses the Python/.NET boundary, and Cortical Labs pointed to
latency as the main thing separating their stack from everyone else's. We needed
to know whether that boundary is actually costing us.

This branch runs the **same measurements** by calling `McsUsbNet.dll` directly
from C#, with no Python anywhere in the loop.

- **If both branches report the same latency** → pythonnet is not the problem. The
  delay is hardware/driver-bound, and the next thing to look at is the IFB-C
  onboard signal processor, which could run the decision rule on the board.
- **If C# is much faster** → the boundary is the problem, and a native layer
  (or an `MCSEnv` backend for BrainDance) is worth the effort.

## Building

Uses the C# compiler that ships with Windows — **no .NET SDK install needed**.

```bat
build.bat
```

`build.bat` also copies `McsUsbNet.dll` next to the exe and runs `Unblock-File`
on it. Without that, .NET refuses to load the assembly because it was downloaded
and sits under OneDrive.

## Running

```bat
LatencyTest.exe                  :: record-only timing
LatencyTest.exe --stim           :: + round-trip latency   (SALINE ONLY)
LatencyTest.exe --stim --stim-steps 100 --seconds 10
```

Writes `latency_csharp.csv`. Compare against `latency_pythonnet.csv` from the
other branch — same metric names, so the rows line up.

## Status

Compiles clean against `McsUsbNet.dll` v5.1.36.0 and runs. Verified as far as
possible without the rig attached (reaches "No MEA device found" and exits).

## Safety

Stimulation is opt-in behind `--stim` and defaults to 100 DAC steps, deliberately
small. The program queries and prints the device's real voltage range and
resolution before stimulating, so you can see what that amplitude actually means
in millivolts before raising it.

Run the stimulation phase on **saline only** until the units are confirmed. Saline
is also the right medium for this measurement: the artifact is large and
unambiguous, and there are no spikes to confuse it with.
