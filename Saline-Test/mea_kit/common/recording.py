"""
Loading recordings and pulse tables.

Abbas, Oct 21 2026 (new).
Supported inputs:
  * our recorder's blocks:  <name>.bin + <name>.json  (int32, sample-major, all streams)
  * MCS HDF5 exported by Multi Channel DataManager (.h5)   - if we record with MCS software instead
  * .npz with keys data (channels x samples), fs, [labels]
Everything is read lazily (memory-mapped) and handed out ONE CHANNEL AT A TIME, so a 5-minute
60-channel block at 50 kHz (3.6 GB as float32) never has to sit in RAM at once.
"""
import csv
import json
import os

import numpy as np


class Recording:
    def __init__(self, fs, n_channels, n_samples, get_channel, labels=None, meta=None, get_stream=None, n_streams=None):
        self.fs = float(fs)
        self.n_channels = int(n_channels)
        self.n_samples = int(n_samples)
        self._get = get_channel
        self._get_stream = get_stream
        self.n_streams = n_streams if n_streams is not None else n_channels
        self.labels = labels or [str(i) for i in range(n_channels)]
        self.meta = meta or {}

    def channel(self, c, start=0, stop=None):
        """float64 trace of analog channel c (counts, or uV if the source is calibrated)."""
        return np.asarray(self._get(c, start, stop), dtype=np.float64)

    def stream(self, s, start=0, stop=None):
        """Raw int stream s (includes digital / sideband streams after the analog ones)."""
        if self._get_stream is None:
            raise ValueError("this recording has no extra streams")
        return self._get_stream(s, start, stop)

    @property
    def duration_s(self):
        return self.n_samples / self.fs


def _load_block(prefix):
    with open(prefix + ".json") as f:
        meta = json.load(f)
    n_streams = int(meta["n_streams"])
    raw = np.memmap(prefix + ".bin", dtype=np.int32, mode="r")
    n_samples = raw.size // n_streams
    raw = raw[: n_samples * n_streams].reshape(n_samples, n_streams)
    analog = meta.get("analog_streams", list(range(60)))
    scale = meta.get("uv_per_count")  # None = keep raw counts (fine: all metrics are in noise units)

    def get_channel(c, start=0, stop=None):
        x = np.asarray(raw[start:stop, analog[c]], dtype=np.float64)
        return x * scale if scale else x

    def get_stream(s, start=0, stop=None):
        return np.asarray(raw[start:stop, s])

    return Recording(meta["fs"], len(analog), n_samples, get_channel, meta.get("labels"), meta, get_stream, n_streams)


def _load_mcs_h5(path):
    import h5py
    f = h5py.File(path, "r")
    st = f["Data"]["Recording_0"]["AnalogStream"]["Stream_0"]
    data = st["ChannelData"]
    info = st["InfoChannel"][()]
    adz = info["ADZero"].astype(np.float64)
    conv = (info["ConversionFactor"].astype(np.float64) * 10.0 ** info["Exponent"].astype(np.float64)) * 1e6  # -> uV
    fs = 1e6 / float(info["Tick"][0])
    labels = [l.decode() if isinstance(l, bytes) else str(l) for l in info["Label"]]

    def get_channel(c, start=0, stop=None):
        return (np.asarray(data[c, start:stop], dtype=np.float64) - adz[c]) * conv[c]

    meta = {"source": os.path.abspath(path), "units": "uV"}
    return Recording(fs, data.shape[0], data.shape[1], get_channel, labels, meta)


def _load_npz(path):
    z = np.load(path, allow_pickle=True)
    d = z["data"]
    labels = [str(x) for x in z["labels"]] if "labels" in z.files else None

    def get_channel(c, start=0, stop=None):
        return d[c, start:stop]

    return Recording(float(z["fs"]), d.shape[0], d.shape[1], get_channel, labels, {"source": path})


def load_recording(path):
    """Path to <block>.json/.bin (with or without extension), .h5, or .npz."""
    p = str(path)
    for ext in (".json", ".bin"):
        if p.endswith(ext):
            p = p[: -len(ext)]
    if os.path.exists(p + ".json") and os.path.exists(p + ".bin"):
        return _load_block(p)
    if p.endswith((".h5", ".hdf5")):
        return _load_mcs_h5(p)
    if p.endswith(".npz"):
        return _load_npz(p)
    raise FileNotFoundError(f"don't know how to load {path}")


# ---------------- pulse tables ----------------
PULSE_COLUMNS = ["pulse_sample", "cmd_index", "kind", "side", "electrodes", "generator", "mode",
                 "amplitude", "phase_us", "polarity", "window_start_sample", "window_ms", "source"]


def save_pulses(rows, path):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=PULSE_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: (";".join(map(str, r[k])) if isinstance(r.get(k), (list, tuple)) else r.get(k, "")) for k in PULSE_COLUMNS})


def load_pulses(path):
    """Returns a list of dicts with ints/lists parsed. 'electrodes' -> list[int]."""
    out = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            d = dict(r)
            d["pulse_sample"] = int(float(d["pulse_sample"]))
            d["electrodes"] = [int(x) for x in str(d.get("electrodes", "")).split(";") if x.strip() != ""]
            for k in ("cmd_index", "window_start_sample"):
                d[k] = int(float(d[k])) if d.get(k) not in (None, "") else None
            for k in ("phase_us", "window_ms", "amplitude"):
                d[k] = float(d[k]) if d.get(k) not in (None, "") else None
            out.append(d)
    return out
