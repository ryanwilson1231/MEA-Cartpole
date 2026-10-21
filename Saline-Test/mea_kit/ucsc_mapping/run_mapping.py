"""
Run the UCSC-style mapping on a session folder. Abbas, Oct 21 2026 (new).

    python -m mea_kit.ucsc_mapping.run_mapping --session S --version v2 --cleaner salpa
    python -m mea_kit.ucsc_mapping.run_mapping --session S --version all
    python -m mea_kit.ucsc_mapping.run_mapping --compare mapA.json mapB.json [mapC.json]   (drift)
Needs blocks: baseline (spontaneous) + sweep. On saline this is the NULL TEST: version 2 should report
~0 significant pairs; whatever version 1 reports there is artifact/noise, not connectivity.
--blind-ms auto  -> reads the benchmark's measured blind period for the chosen cleaner (falls back to 2 ms).
"""
import argparse
import json
import os

import numpy as np

from ..saline_benchmark.report import NpEncoder
from ..saline_benchmark.session import Block
from . import drift, v1_ucsc_faithful, v2_ours_adapted, v3_auto_select
from ..hardware import config as HC


def auto_blind(session, cleaner):
    p = os.path.join(session, "benchmark", "results.json")
    try:
        with open(p) as f:
            res = json.load(f)["results"]
        for row in ("R2_current", "R1_normal", "R3_short"):
            v = res.get(row, {}).get(cleaner or "none", {}).get("blind_other_median_ms")
            if v is not None and np.isfinite(v):
                return max(0.5, float(v))
    except Exception:  # noqa: BLE001
        pass
    return 2.0


def _load_map(path):
    with open(path) as f:
        m = json.load(f)
    for k, v in m.items():
        if k.startswith("W") and isinstance(v, dict):
            for kk in ("C1corr", "significant", "C1_post", "C1_pre", "p"):
                if kk in v:
                    v[kk] = np.array(v[kk], dtype=float if kk != "significant" else bool)
    return m


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--session")
    ap.add_argument("--version", default="all", choices=["v1", "v2", "v3", "all"])
    ap.add_argument("--cleaner", default="salpa")
    ap.add_argument("--blind-ms", default="auto")
    ap.add_argument("--compare", nargs="+")
    ap.add_argument("--zones", default="fixed", choices=["fixed", "learned"])
    args = ap.parse_args(argv)
    if args.compare:
        maps = [_load_map(p) for p in args.compare]
        print(json.dumps(drift.compare(*maps), indent=1, cls=NpEncoder))
        return
    out = os.path.join(args.session, "mapping")
    os.makedirs(out, exist_ok=True)
    spont = Block(args.session, "baseline").rec
    sweep = Block(args.session, "sweep")
    blind = auto_blind(args.session, args.cleaner) if args.blind_ms == "auto" else float(args.blind_ms)
    cparams = None
    if args.cleaner == "salpa":
        from ..common.pulses import estimate_hold_ms
        smp = [p["pulse_sample"] for p in sweep.pulses]
        ch = sorted({c for p in sweep.pulses for c in sweep.channels_of(p["electrodes"])})
        cparams = {"forcepeg_ms": max(1.0, estimate_hold_ms(sweep.rec, smp, ch) + 0.3)}
    summary = []
    r2 = None
    if args.version in ("v1", "all"):
        r1 = v1_ucsc_faithful.run(spont, sweep, cleaner=None)
        with open(os.path.join(out, "v1.json"), "w") as f:
            json.dump(r1, f, cls=NpEncoder)
        summary.append(f"v1 (UCSC as-is, no cleaning): {'NULL MODE (nothing fires) - ' if r1['null_mode'] else ''}"
                       f"{r1['n_pairs_c1_over_0.2']} pairs with C1 > 0.2 at 10 ms. Roles suggested: {r1['roles_suggestion']}")
    if args.version in ("v2", "v3", "all"):
        r2 = v2_ours_adapted.run(spont, sweep, cleaner=args.cleaner, cleaner_params=cparams, blind_ms=blind)
        r2["blind_ms_used"] = blind
        with open(os.path.join(out, f"v2_{args.cleaner}.json"), "w") as f:
            json.dump(r2, f, cls=NpEncoder)
        W = r2["chosen_window_ms"]
        summary.append(f"v2 (ours, cleaner={args.cleaner}, window starts at {blind:.1f} ms): "
                       f"{'NULL MODE (saline) - ' if r2['null_mode'] else ''}{r2[f'W{int(W)}']['n_significant']} significant pairs "
                       f"of {r2[f'W{int(W)}']['n_tested']} at {W:.0f} ms (10 ms: {r2['W10']['n_significant']}, 18 ms: {r2['W18']['n_significant']}). "
                       f"Bursty inputs: {r2['bursty_inputs']}")
    if args.version in ("v3", "all") and r2 is not None:
        r3 = v3_auto_select.run(r2, zones=args.zones, left=HC.LEFT, right=HC.RIGHT)
        with open(os.path.join(out, "v3.json"), "w") as f:
            json.dump(r3, f, cls=NpEncoder)
        summary.append(f"v3 ({args.zones} zones): best = {r3['best']}  ({r3['n_pairs_scored']} pairs scored)")
    with open(os.path.join(out, "summary.md"), "w") as f:
        f.write("\n\n".join(summary) + "\n")
    print("\n".join(summary))


if __name__ == "__main__":
    main()
