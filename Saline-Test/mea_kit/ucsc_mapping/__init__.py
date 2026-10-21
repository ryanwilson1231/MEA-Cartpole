"""
UCSC-style network mapping (Robbins et al., Cell Reports 2026 / bioRxiv 2024), three versions.
Abbas, Oct 21 2026 (new).

  scoring.py           the shared UCSC scoring: spikes, eta ranking, response tensor R[k,i,j], C1, Cm, bursts
  v1_ucsc_faithful.py  as close to UCSC as our rig allows: 5xRMS units + footprint merge, top-32 by eta,
                       3 SD response spikes, C1 (10 or 18 ms), Cm (200 ms), median+3MAD bursts, UCSC rubric
  v2_ours_adapted.py   Syrine's 4 adaptations for a 60-electrode MEA: electrode = unit, C1 corrected for
                       background firing (pre-pulse window) + exact test + FDR, both windows with the better
                       one picked from data, window starts after the measured blind period
  v3_auto_select.py    automatic role selection (UCSC chose by hand): searches all input pairs, scores how
                       much each input drives its own decoder zone over the other, drops bursty /
                       artifact-prone electrodes
  drift.py             map-to-map comparison: count only changes bigger than the natural drift
  synthetic.py         fake culture with KNOWN connections, to check the code finds them
  run_mapping.py       CLI on a session folder (baseline = spontaneous recording, sweep = stimulation sweep)
"""
