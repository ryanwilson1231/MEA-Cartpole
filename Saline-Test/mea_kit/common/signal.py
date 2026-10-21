"""
Filters, noise estimates and spike detection shared by every package.

Abbas, Oct 21 2026 (new).
Why: every package must detect spikes the SAME way, and the same way the game does,
otherwise the benchmark would score something different from what the decoder sees.
`game_count_spikes` is a copy of count_spikes() in Baseline-Protocol/Hardware/mea_device.py.
"""
import numpy as np
from scipy.signal import butter, sosfiltfilt

# Same constants as Baseline-Protocol/Hardware/mea_device.py
GAME_BAND_HZ = (300.0, 3000.0)
GAME_FILTER_ORDER = 2
GAME_THRESHOLD_SD = 5.0

_sos_cache = {}


def bandpass_sos(fs, band=GAME_BAND_HZ, order=GAME_FILTER_ORDER):
    key = (float(fs), tuple(band), order)
    if key not in _sos_cache:
        _sos_cache[key] = butter(order, list(band), btype="bandpass", fs=fs, output="sos")
    return _sos_cache[key]


def bandpass(x, fs, band=GAME_BAND_HZ, order=GAME_FILTER_ORDER):
    """Zero-phase band-pass along the last axis (same filter as the game's decoder)."""
    return sosfiltfilt(bandpass_sos(fs, band, order), np.asarray(x, dtype=np.float64), axis=-1)


def mad_sigma(x):
    """Noise level the way mea_device.py does it: median(|x|) / 0.6745 (x already band-passed)."""
    return np.median(np.abs(x), axis=-1) / 0.6745


def hf_sigma(x):
    """Robust high-frequency noise of a RAW trace from its first difference (ignores slow drift/LFP)."""
    d = np.diff(np.asarray(x, dtype=np.float64), axis=-1)
    return np.median(np.abs(d - np.median(d, axis=-1, keepdims=True)), axis=-1) / 0.6745 / np.sqrt(2.0)


def game_count_spikes(voltages, fs, threshold_sd=GAME_THRESHOLD_SD):
    """
    EXACT copy of count_spikes() from Baseline-Protocol/Hardware/mea_device.py.
    voltages: (channels, samples) for ONE decoding window. Returns spikes per channel.
    """
    filtered = bandpass(voltages, fs)
    noise = np.median(np.abs(filtered), axis=1) / 0.6745
    below = filtered < -threshold_sd * noise[:, None]
    new_crossings = below[:, 1:] & ~below[:, :-1]
    return new_crossings.sum(axis=1)


def masked_count_spikes(voltages, fs, invalid=None, threshold_sd=GAME_THRESHOLD_SD):
    """Same as game_count_spikes, but samples a cleaner blanked (invalid) are ignored both for the
    noise estimate and for counting. This is how a cleaner has to be plugged into the game's decoder:
    without it, the edges of every blanked stretch look like spikes (found Oct 21 in the dry run)."""
    filtered = bandpass(voltages, fs)
    if invalid is None:
        invalid = np.zeros(filtered.shape, bool)
    valid = ~invalid
    out = np.zeros(filtered.shape[0], int)
    for c in range(filtered.shape[0]):
        v = filtered[c][valid[c]]
        if v.size < 10:
            continue
        noise = np.median(np.abs(v)) / 0.6745
        below = (filtered[c] < -threshold_sd * noise) & valid[c]
        out[c] = int(np.sum(below[1:] & ~below[:-1]))
    return out


def crossings(xf, sigma, threshold_sd=GAME_THRESHOLD_SD, valid=None):
    """Indices where a band-passed trace newly crosses below -threshold_sd*sigma.
    Samples flagged invalid (blanked) never count."""
    below = xf < -threshold_sd * sigma
    if valid is not None:
        below &= valid
    idx = np.flatnonzero(below[1:] & ~below[:-1]) + 1
    return idx


def trough_after(xf, idx, fs, search_ms=1.0):
    """For each crossing index, the index of the minimum within search_ms after it."""
    n = int(search_ms * fs / 1000)
    out = np.empty(len(idx), int)
    for k, i in enumerate(idx):
        seg = xf[i: i + n]
        out[k] = i + int(np.argmin(seg)) if len(seg) else i
    return out


def spike_template(fs, ms=2.0):
    """Generic extracellular spike (negative trough ~0.3 ms after onset, small rebound), peak = -1."""
    t = np.arange(int(ms * fs / 1000)) / fs * 1000.0
    w = -np.exp(-((t - 0.30) / 0.12) ** 2) + 0.30 * np.exp(-((t - 0.75) / 0.25) ** 2)
    i = int(np.argmin(w))
    return (w / -w[i]).astype(np.float64), i
