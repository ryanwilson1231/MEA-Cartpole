"""
mea_kit: saline-test and network-mapping toolkit for the MEA-Cartpole project.

Abbas, Oct 21 2026 (new). Built for the Oct 22 saline test on the MEA2100-Mini-60.
Sub-packages (each usable on its own):
  common/            loading recordings, filters, spike detection, pulse tables
  artifact_removal/  4 artifact removers with one shared interface (SALPA, blanking, template, SpikeInterface)
  saline_benchmark/  scores every remover on a real saline recording and builds the pivot table
  ucsc_mapping/      UCSC-style network mapping (v1 faithful, v2 adapted to our 60-electrode rig, v3 automatic role selection)
  hardware/          saline stimulation protocol for the lab PC (pythonnet + McsUsbNet.dll) with a dry-run simulator
"""
__version__ = "0.1.0"
