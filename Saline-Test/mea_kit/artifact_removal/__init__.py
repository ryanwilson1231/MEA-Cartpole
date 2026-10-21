"""
Artifact removers. Abbas, Oct 21 2026 (new).

All four share ONE interface so the benchmark can swap them:

    result = clean_channel(x, fs, pulses, groups=None, **params)
      x       1-D raw trace of one channel (counts or uV)
      pulses  sorted pulse-onset samples (np.int64)
      groups  optional per-pulse group id (pulses with the same id share an artifact shape)
      -> CleanResult(x=cleaned trace, invalid=bool mask of samples that carry no data, info={...})

Removers (see each module for the why):
  none            reference: do nothing
  salpa           SALPA (Wagenaar & Potter 2002) local cubic fit, via the `salpa` pip package
  blank           simple blanking: replace a window after each pulse (Abbas' original 3 ms idea)
  template        average the artifact over repeats and subtract it
  spikeinterface  spikeinterface.preprocessing.remove_artifacts
  localpoly       pure-Python SALPA-like fallback (only if the salpa package won't install)
"""
from .base import CleanResult, available_removers, get_remover, REMOVER_DESCRIPTIONS  # noqa: F401
