"""
Load a session folder written by hardware/saline_protocol.py. Abbas, Oct 21 2026 (new).
"""
import csv
import json
import os

from ..common.recording import load_recording
from ..common.pulses import refine_from_commands


def load_commands(path):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            d = dict(r)
            d["electrodes"] = [int(x) for x in d.get("electrodes", "").split(";") if x.strip() != ""]
            d["onsets_us"] = [float(x) for x in d.get("onsets_us", "").split(";") if x.strip() != ""]
            for k in ("sample_at_send", "cmd_index", "generator"):
                d[k] = int(float(d[k])) if d.get(k) not in (None, "") else None
            for k in ("amplitude", "phase_us", "window_ms", "route_ms", "send_ms", "t_perf"):
                d[k] = float(d[k]) if d.get(k) not in (None, "") else None
            rows.append(d)
    return rows


class Block:
    def __init__(self, folder, name, electrode_to_channel=None):
        self.name = name
        self.rec = load_recording(os.path.join(folder, name))
        self.meta = self.rec.meta
        self.commands = load_commands(os.path.join(folder, f"{name}_commands.csv"))
        self.e2c = electrode_to_channel
        self.pulses, self.pulse_source = ([], "no stimulation")
        if self.commands:
            self.pulses, self.pulse_source = refine_from_commands(self.rec, self.commands, electrode_to_channel)

    def channels_of(self, electrodes):
        m = self.e2c or {}
        return sorted({m.get(e, e) for e in electrodes})


def load_session(folder):
    with open(os.path.join(folder, "session.json")) as f:
        session = json.load(f)
    names = [b for b in session["blocks"] if os.path.exists(os.path.join(folder, b + ".json"))]
    return session, names
