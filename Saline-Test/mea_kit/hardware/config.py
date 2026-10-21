"""
Saline-test configuration. Abbas, Oct 21 2026 (new).

Rows of the pivot table = stimulation conditions below. Every condition uses cathodic-first
(negative-first) biphasic pulses, as agreed with the team (Wagenaar et al. 2003: cathodic-first
pulses evoke responses, anodic-first evoked nothing).
Units: voltage amplitudes in uV (same as STIM_AMPLITUDE_UV in mea_device.py),
       current amplitudes in nA (DLL reports current ranges in nA - probe_api.py checks this).
CHECK THE AMPLITUDES WITH THE LAB LEAD before running. They only matter for electrode safety in
saline (no cells), but too much charge can damage electrodes.
"""

N_CHANNELS = 60
HEADSTAGE = 0                       # SCU port of the headstage (HS1 = 0), same as mea_device.py
SAMPLE_RATE = 50_000
LEFT = list(range(0, 30))           # same split as feedback.py
RIGHT = list(range(30, 60))

# --- safety limits (refuse to run above these unless --allow-high-charge) ---
MAX_CURRENT_NA = 30_000             # 30 uA
MAX_VOLTAGE_UV = 150_000            # 150 mV (the game currently uses 75 mV)
MAX_CHARGE_NC_PER_PHASE = 4.0       # current mode: amplitude x phase width

# --- game-style timing (copies run_hardware.py / mea_device.py) ---
WINDOW_MS = 100
PULSES_PER_WINDOW = 2               # predictable stim: pulses at 0 and 50 ms
STEP_OVERHEAD_MS = 5                # time the game spends decoding + stepping between windows

# --- the pivot-table rows ---
CONDITIONS = {
    "R1_normal": dict(short="R1 Normal stim",
        label="Normal stim: voltage 75 mV, 200 us/phase (today's game pulse, made cathodic-first)",
        mode="voltage", amplitude=75_000, phase_us=200, blanking=True, layout="halves"),
    "R2_current": dict(short="R2 Current-mode",
        label="Current-mode 10 uA, 200 us/phase",
        mode="current", amplitude=10_000, phase_us=200, blanking=True, layout="halves"),
    "R3_short": dict(short="R3 Short stim",
        label="Short stim: current-mode 10 uA, 100 us/phase",
        mode="current", amplitude=10_000, phase_us=100, blanking=True, layout="halves"),
    "R4_blanking_off": dict(short="R4 Hardware blanking OFF",
        label="Hardware blanking OFF (normal stim) - shows how much blanking helps. ASK KAI FIRST",
        mode="voltage", amplitude=75_000, phase_us=200, blanking=False, layout="halves", optional=True),
    "R5_moved_zones": dict(short="R5 Moved decoder zones",
        label="2 input electrodes per side, decoder zones away from inputs",
        mode="current", amplitude=10_000, phase_us=200, blanking=True, layout="few_inputs"),
}

# Input electrodes for R5 (placeholders in the middle of each half). After the sweep block,
# electrode_map in the report suggests better ones; edit here for the next session.
FEW_INPUTS = {"left": [12, 13], "right": [42, 43]}

# --- block sizes ---
BASELINE_S = 60                     # no stimulation: noise floor + channel health
GAME_WINDOWS = 150                  # per condition (~16 s)
SWEEP = dict(electrodes="all", pulses=10, rate_hz=2.0, condition="R2_current")   # mapping dry run
AMP_SERIES = dict(electrode=12, amplitudes_na=[5_000, 10_000, 20_000], pulses=30, rate_hz=2.0, phase_us=200)
SWITCH_TEST = dict(electrodes=[12, 13, 42, 43], spacings_ms=[5, 10, 20], reps=10, condition="R2_current")

# Sideband timings copied from mea_device.py (_send): CreateSideband(active, syncout, durations, 40, 800, 40)
SIDEBAND_TIMES = (40, 800, 40)
