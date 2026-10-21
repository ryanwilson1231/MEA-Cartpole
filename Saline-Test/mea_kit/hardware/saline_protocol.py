"""
Saline test protocol. Abbas, Oct 21 2026 (new).

Runs the blocks for tomorrow and writes one session folder:
  baseline        60 s, no stimulation          -> noise floor, are all 60 channels alive?
  R1..R5          game-style stimulation, one block per pivot-table row (see config.CONDITIONS)
  sweep           one electrode at a time, 10 pulses at 2 Hz each -> electrode map + UCSC "null map"
  amp_series      one electrode, 3 amplitudes    -> how artifact size/length grows with amplitude
  switch          can one generator hop electrodes every 5 / 10 / 20 ms?  (Syrine's open question)
Each block -> <block>.bin/.json (all streams) + <block>_commands.csv (every SendStart we issued).

Usage (lab PC, MEA + saline):   python -m mea_kit.hardware.saline_protocol --out sessions/oct22_saline
Dry run anywhere (no hardware): python -m mea_kit.hardware.saline_protocol --dry-run --out sessions/dry
"""
import argparse
import csv
import json
import os
import platform
import subprocess
import sys
import time

import numpy as np

from . import config as C
from .stim_pulses import check_safety, predictable_onsets, pulse_train, silent

ALL_BLOCKS = ["baseline", "R1_normal", "R2_current", "R3_short", "R5_moved_zones", "sweep", "amp_series", "switch"]


class CommandLog:
    COLS = ["cmd_index", "block", "kind", "side", "electrodes", "generator", "mode", "amplitude", "phase_us",
            "polarity", "onsets_us", "window_ms", "sample_at_send", "t_perf", "route_ms", "send_ms"]

    def __init__(self, path):
        self.path = path
        self.rows = []

    def add(self, **r):
        r["cmd_index"] = len(self.rows)
        self.rows.append(r)

    def save(self):
        with open(self.path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=self.COLS, extrasaction="ignore")
            w.writeheader()
            for r in self.rows:
                w.writerow({k: (";".join(map(str, r[k])) if isinstance(r.get(k), (list, tuple)) else r.get(k, "")) for k in self.COLS})


def _routing(layout):
    if layout == "halves":
        return {**{e: 0 for e in C.LEFT}, **{e: 1 for e in C.RIGHT}}
    if layout == "few_inputs":
        return {**{e: 0 for e in C.FEW_INPUTS["left"]}, **{e: 1 for e in C.FEW_INPUTS["right"]}}
    raise ValueError(layout)


def run_game_block(dev, log, name, cond, n_windows, rng, allow_high):
    check_safety(cond["mode"], cond["amplitude"], cond["phase_us"], allow_high)
    dev.set_mode(cond["mode"])
    dev.set_blanking(cond["blanking"])
    assign = _routing(cond["layout"])
    route_ms = dev.route(assign)
    sides = {0: [e for e, g in assign.items() if g == 0], 1: [e for e, g in assign.items() if g == 1]}
    W = C.WINDOW_MS
    for w in range(n_windows):
        unpredictable = rng.random() < 0.2          # the game sends ~both kinds; most windows predictable
        if unpredictable:
            slots = W * 1000 // (2 * cond["phase_us"])
            ons = {g: sorted(int(s) * 2 * cond["phase_us"] for s in rng.choice(slots, C.PULSES_PER_WINDOW, replace=False)) for g in (0, 1)}
            trains = {g: pulse_train(ons[g], W, cond["amplitude"], cond["phase_us"]) for g in (0, 1)}
            sample, send_ms = dev.send(trains, W)
            for g in (0, 1):
                log.add(block=name, kind="unpredictable", side="left" if g == 0 else "right", electrodes=sides[g], generator=g,
                        mode=cond["mode"], amplitude=cond["amplitude"], phase_us=cond["phase_us"], polarity="cathodic_first",
                        onsets_us=ons[g], window_ms=W, sample_at_send=sample, t_perf=time.perf_counter(), route_ms=0, send_ms=send_ms)
        else:
            g = int(rng.integers(2))
            ons = predictable_onsets(W)
            trains = {g: pulse_train(ons, W, cond["amplitude"], cond["phase_us"]), 1 - g: silent(W)}
            sample, send_ms = dev.send(trains, W)
            log.add(block=name, kind="predictable", side="left" if g == 0 else "right", electrodes=sides[g], generator=g,
                    mode=cond["mode"], amplitude=cond["amplitude"], phase_us=cond["phase_us"], polarity="cathodic_first",
                    onsets_us=ons, window_ms=W, sample_at_send=sample, t_perf=time.perf_counter(),
                    route_ms=route_ms if w == 0 else 0, send_ms=send_ms)
        dev.wait_ms(W + C.STEP_OVERHEAD_MS)


def run_single_pulses(dev, log, name, kind, electrode, cond, n, rate_hz, allow_high, amplitude=None, generator=0):
    amp = cond["amplitude"] if amplitude is None else amplitude
    check_safety(cond["mode"], amp, cond["phase_us"], allow_high)
    W = 10  # ms of waveform per command
    for k in range(n):
        sample, send_ms = dev.send({generator: pulse_train([0], W, amp, cond["phase_us"])}, W)
        log.add(block=name, kind=kind, side="", electrodes=[electrode], generator=generator, mode=cond["mode"], amplitude=amp,
                phase_us=cond["phase_us"], polarity="cathodic_first", onsets_us=[0], window_ms=W,
                sample_at_send=sample, t_perf=time.perf_counter(), route_ms=0, send_ms=send_ms)
        dev.wait_ms(1000.0 / rate_hz - send_ms)


def run_block(dev, out, name, args, rng):
    log = CommandLog(os.path.join(out, f"{name}_commands.csv"))
    meta = {"block": name, "started": time.strftime("%Y-%m-%d %H:%M:%S"), "device": dev.name}
    if name in C.CONDITIONS:
        meta.update({"condition": name, "row_label": C.CONDITIONS[name]["label"], "condition_params": C.CONDITIONS[name]})
        if name == "R5_moved_zones":
            meta["few_inputs"] = C.FEW_INPUTS
    dev.start_block(os.path.join(out, name), meta)
    try:
        if name == "baseline":
            dev.set_blanking(True)
            dev.wait_ms(args.baseline_s * 1000)
        elif name in C.CONDITIONS:
            run_game_block(dev, log, name, C.CONDITIONS[name], args.game_windows, rng, args.allow_high_charge)
        elif name == "sweep":
            cond = C.CONDITIONS[C.SWEEP["condition"]]
            dev.set_mode(cond["mode"]); dev.set_blanking(cond["blanking"])
            elecs = list(range(C.N_CHANNELS)) if C.SWEEP["electrodes"] == "all" else C.SWEEP["electrodes"]
            if args.sweep_electrodes:
                elecs = []
                for part in args.sweep_electrodes.split(","):
                    a, _, b = part.partition("-")
                    elecs += list(range(int(a), int(b or a) + 1))
            for e in elecs:
                dev.route({e: 0})
                dev.wait_ms(50)
                run_single_pulses(dev, log, name, "sweep", e, cond, args.sweep_pulses, C.SWEEP["rate_hz"], args.allow_high_charge)
        elif name == "amp_series":
            a = C.AMP_SERIES
            cond = dict(C.CONDITIONS["R2_current"], phase_us=a["phase_us"])
            dev.set_mode("current"); dev.set_blanking(True)
            dev.route({a["electrode"]: 0})
            for amp in a["amplitudes_na"]:
                run_single_pulses(dev, log, name, f"amp_{amp}", a["electrode"], cond, a["pulses"], a["rate_hz"], args.allow_high_charge, amplitude=amp)
        elif name == "switch":
            s = C.SWITCH_TEST
            cond = C.CONDITIONS[s["condition"]]
            dev.set_mode(cond["mode"]); dev.set_blanking(True)
            W = 2
            for spacing in s["spacings_ms"]:
                # (a) ONE generator, re-routed to the next electrode before every pulse
                for rep in range(s["reps"]):
                    for e in s["electrodes"]:
                        r_ms = dev.route({e: 0})
                        sample, send_ms = dev.send({0: pulse_train([0], W, cond["amplitude"], cond["phase_us"])}, W)
                        log.add(block=name, kind=f"reroute_{spacing}ms", side="", electrodes=[e], generator=0, mode=cond["mode"],
                                amplitude=cond["amplitude"], phase_us=cond["phase_us"], polarity="cathodic_first", onsets_us=[0],
                                window_ms=W, sample_at_send=sample, t_perf=time.perf_counter(), route_ms=r_ms, send_ms=send_ms)
                        dev.wait_ms(max(0.0, spacing - r_ms - send_ms))
                    dev.wait_ms(300)
                # (b) fallback from Syrine's doc: TWO generators pre-routed, alternate between them
                a_e, b_e = s["electrodes"][0], s["electrodes"][1]
                dev.route({a_e: 0, b_e: 1})
                for rep in range(s["reps"] * 2):
                    g = rep % 2
                    sample, send_ms = dev.send({g: pulse_train([0], W, cond["amplitude"], cond["phase_us"])}, W)
                    log.add(block=name, kind=f"alternate_{spacing}ms", side="", electrodes=[a_e if g == 0 else b_e], generator=g,
                            mode=cond["mode"], amplitude=cond["amplitude"], phase_us=cond["phase_us"], polarity="cathodic_first",
                            onsets_us=[0], window_ms=W, sample_at_send=sample, t_perf=time.perf_counter(), route_ms=0, send_ms=send_ms)
                    dev.wait_ms(max(0.0, spacing - send_ms))
                dev.wait_ms(300)
        else:
            raise ValueError(f"unknown block {name}")
    finally:
        dev.set_blanking(True)   # always leave hardware blanking ON after every block
        m = dev.stop_block({"commands": len(log.rows)})
        log.save()
    print(f"  {name}: {m['n_samples'] / dev.fs:.1f} s recorded, {len(log.rows)} stim commands")


def git_hash():
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL).decode().strip()
    except Exception:  # noqa: BLE001
        return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--dry-run", action="store_true", help="simulated device, no hardware")
    ap.add_argument("--blocks", default=",".join(ALL_BLOCKS))
    ap.add_argument("--include-blanking-off", action="store_true", help="also run R4 (ask Kai first)")
    ap.add_argument("--game-windows", type=int, default=C.GAME_WINDOWS)
    ap.add_argument("--sweep-pulses", type=int, default=C.SWEEP["pulses"])
    ap.add_argument("--sweep-electrodes", default=None, help='e.g. "0-15" (default: all 60)')
    ap.add_argument("--baseline-s", type=float, default=C.BASELINE_S)
    ap.add_argument("--allow-high-charge", action="store_true")
    ap.add_argument("--dll", default=None)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--notes", default="")
    args = ap.parse_args(argv)
    blocks = [b.strip() for b in args.blocks.split(",") if b.strip()]
    # SAFETY: hardware blanking stays ON in every block. The only block that turns it off is R4, and it
    # runs only with --include-blanking-off (ask Kai first), even if someone lists it in --blocks.
    if "R4_blanking_off" in blocks and not args.include_blanking_off:
        print("Skipping R4_blanking_off: it turns hardware blanking OFF. Add --include-blanking-off only if Kai OK'd it.")
        blocks = [b for b in blocks if b != "R4_blanking_off"]
    if args.include_blanking_off and "R4_blanking_off" not in blocks:
        blocks.insert(blocks.index("R3_short") + 1 if "R3_short" in blocks else 1, "R4_blanking_off")
    # check every stimulus is inside the safety limits BEFORE touching hardware
    for b in blocks:
        if b in C.CONDITIONS:
            c = C.CONDITIONS[b]
            check_safety(c["mode"], c["amplitude"], c["phase_us"], args.allow_high_charge)
    for amp in C.AMP_SERIES["amplitudes_na"]:
        check_safety("current", amp, C.AMP_SERIES["phase_us"], args.allow_high_charge)
    os.makedirs(args.out, exist_ok=True)
    if args.dry_run:
        from .device_fake import FakeDevice
        dev = FakeDevice(seed=args.seed)
    else:
        from .device_mcs import MCSDevice
        dev = MCSDevice(dll_path=args.dll)
    session = {"created": time.strftime("%Y-%m-%d %H:%M:%S"), "blocks": blocks, "dry_run": args.dry_run, "notes": args.notes,
               "git": git_hash(), "python": sys.version.split()[0], "platform": platform.platform(),
               "conditions": C.CONDITIONS, "few_inputs": C.FEW_INPUTS, "sample_rate": C.SAMPLE_RATE}
    with open(os.path.join(args.out, "session.json"), "w") as f:
        json.dump(session, f, indent=1)
    rng = np.random.default_rng(args.seed)
    dev.connect()
    try:
        for b in blocks:
            print(f"Block {b} ...")
            run_block(dev, args.out, b, args, rng)
    except KeyboardInterrupt:
        print("Stopped by user - blocks finished so far are saved.")
    finally:
        dev.close()
    print(f"Session saved in {args.out}. Next: python -m mea_kit.saline_benchmark.run_benchmark --session {args.out}")


if __name__ == "__main__":
    main()
