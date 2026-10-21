"""
Simulated MEA for dry runs. Abbas, Oct 21 2026 (new).

Same interface as MCSDevice, but nothing is plugged in: it keeps a virtual sample clock, remembers
every pulse, and when a block ends it synthesizes saline-like data (noise, DC offsets, slow drift,
NO neurons) plus stimulation artifacts and a sideband stream, written by the same RawBlockWriter.
Why: so the protocol -> files -> benchmark chain can be tested end to end before tomorrow.
The artifact shapes are a GUESS (fast + slow exponentials, hardware-blanking hold, spread to
neighbours). Never trust a method ranking from fake data - only the code paths.
"""
import numpy as np

from . import config as C
from .recorder import RawBlockWriter


def electrode_xy(n=60):
    """MCS-style 8x8 grid minus corners, column-major. Fake geometry only."""
    xy = []
    for x in range(8):
        for y in range(8):
            if x in (0, 7) and y in (0, 7):
                continue
            xy.append((x, y))
    return np.array(xy[:n], float)


class FakeDevice:
    name = "fake"
    N_STREAMS = 64        # 60 analog + digital in + digital out + sideband low + sideband high
    SIDEBAND_STREAM = 62

    def __init__(self, seed=0, noise=10.0, latency_ms=(2.0, 12.0), route_ms_per_change=0.15):
        self.rng = np.random.default_rng(seed)
        self.fs = C.SAMPLE_RATE
        self.noise = noise
        self.latency_ms = latency_ms
        self.route_ms_per_change = route_ms_per_change
        self.xy = electrode_xy()
        self.dc = self.rng.normal(0, 300, C.N_CHANNELS)
        self.gain = self.rng.uniform(0.7, 1.3, C.N_CHANNELS)
        self.assign = {}
        self.blanking = True
        self.mode = "voltage"
        self.read_streams = self.N_STREAMS
        self.n_streams = self.N_STREAMS
        self._block = None

    def connect(self):
        print("FAKE MEA connected (dry run, no hardware).")

    def set_blanking(self, on):
        self.blanking = bool(on)

    def set_mode(self, mode):
        self.mode = mode

    def route(self, assign):
        changes = sum(1 for e in range(C.N_CHANNELS) if self.assign.get(e) != assign.get(e))
        self.assign = dict(assign)
        ms = 0.05 + changes * 2 * self.route_ms_per_change
        if self._block is not None:
            self._block["clock"] += int(ms * self.fs / 1000)
        return ms

    def send(self, trains, window_ms):
        b = self._block
        sample = b["clock"]
        lat = int(self.rng.uniform(*self.latency_ms) * self.fs / 1000)
        for g, (amps, durs, active) in trains.items():
            electrodes = [e for e, gg in self.assign.items() if gg == g]
            # pulse onsets = starts of active segments that follow an inactive one
            t, prev = 0, 0
            for a, d, act in zip(amps, durs, active):
                if act and not prev:
                    b["pulses"].append(dict(sample=sample + lat + int(t * self.fs / 1e6), electrodes=electrodes,
                                            amp=abs(a), phase_us=d, mode=self.mode, blanking=self.blanking))
                prev = act
                t += d
        send_ms = 1.0 + self.rng.uniform(0, 1.0)
        b["clock"] += int(send_ms * self.fs / 1000)
        return sample, send_ms

    def wait_ms(self, ms):
        self._block["clock"] += int(ms * self.fs / 1000)

    def start_block(self, prefix, meta):
        self._block = dict(prefix=prefix, meta=meta, clock=0, pulses=[])

    # ------------- synthesis -------------
    def _artifact_kernel(self, p, d):
        fs = self.fs
        L = int(0.060 * fs)
        t = np.arange(L) / fs * 1000.0
        if p["mode"] == "voltage":
            A = 600.0 * p["amp"] / 75_000 * np.sqrt(p["phase_us"] / 200)
            tf, ts = 0.8, 8.0
        else:
            A = 300.0 * p["amp"] / 10_000 * np.sqrt(p["phase_us"] / 200)
            tf, ts = 0.5, 4.0
        g = 1.0 if d == 0 else 0.3 / d ** 1.5
        k = self.noise * A * g * (np.exp(-t / tf) + 0.08 * np.exp(-t / ts))
        if p["blanking"]:
            k *= 0.25
        return k

    def stop_block(self, extra_meta=None):
        b = self._block
        fs = self.fs
        n = b["clock"] + int(0.2 * fs)
        w = RawBlockWriter(b["prefix"], fs, self.N_STREAMS, b["meta"])
        chunk = int(fs)  # 1 s chunks
        pulses = sorted(b["pulses"], key=lambda q: q["sample"])
        ps = np.array([q["sample"] for q in pulses], int)
        rail = 2500.0 * self.noise
        hold_extra = int(0.8e-3 * fs)
        for a in range(0, n, chunk):
            m = min(chunk, n - a)
            data = np.zeros((self.N_STREAMS, m), np.int32)
            tt = (a + np.arange(m)) / fs
            sel = np.flatnonzero((ps >= a - int(0.06 * fs)) & (ps < a + m))
            for c in range(C.N_CHANNELS):
                x = self.rng.normal(0, self.noise, m) + self.dc[c] + 30 * np.sin(2 * np.pi * 0.5 * tt + c)
                for i in sel:
                    p = pulses[i]
                    if not p["electrodes"]:
                        continue
                    d = np.min(np.hypot(*(self.xy[p["electrodes"]] - self.xy[c]).T)) if c not in p["electrodes"] else 0.0
                    if d > 4:
                        continue
                    sign = 1.0 if (c * 7 + sum(p["electrodes"]) * 3) % 5 < 3 else -1.0   # fixed per channel/stim site
                    k = self._artifact_kernel(p, d) * self.gain[c] * sign
                    s0 = p["sample"] - a
                    lo, hi = max(0, s0), min(m, s0 + len(k))
                    if hi > lo:
                        x[lo:hi] += k[lo - s0: hi - s0]
                    width = 2 * int(p["phase_us"] * fs / 1e6)
                    if p["blanking"]:
                        h0, h1 = max(0, s0), min(m, s0 + width + hold_extra)
                        if h1 > h0:
                            x[h0:h1] = x[h0 - 1] if h0 > 0 else self.dc[c]
                    elif d == 0:
                        h0, h1 = max(0, s0), min(m, s0 + width + int(0.3e-3 * fs))
                        x[h0:h1] = self.dc[c] + rail
                np.clip(x, self.dc[c] - rail, self.dc[c] + rail, out=x)
                data[c] = np.round(x).astype(np.int32)
            sb = np.zeros(m, np.int32)
            for i in sel:
                p = pulses[i]
                s0 = p["sample"] - a
                width = 2 * int(p["phase_us"] * fs / 1e6)
                sb[max(0, s0): max(0, min(m, s0 + width))] |= 1
            data[self.SIDEBAND_STREAM] = sb
            w.push(data)
        extra = {"fake": True, "true_pulse_samples": [int(q["sample"]) for q in pulses]}
        extra.update(extra_meta or {})
        self._block = None
        return w.close(extra)

    def close(self):
        print("FAKE MEA closed.")
