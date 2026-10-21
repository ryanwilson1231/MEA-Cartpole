"""
Run the saline benchmark on a session folder. Abbas, Oct 21 2026 (new).

    python -m mea_kit.saline_benchmark.run_benchmark --session sessions/oct22_saline
Options:
    --removers none,salpa,blank,template,spikeinterface   (columns; default = all available)
    --channels 0-59          analyse a subset to go faster (e.g. "0-9,30-39")
    --episodes path/to/episode_lengths.csv   result of run_hardware.py played on saline
Outputs into <session>/benchmark/: report.html (colour-coded pivot), report.md, pivot_*.csv,
results.json, example_traces_<row>.png
"""
import argparse
import json
import os
import time

import numpy as np

from ..artifact_removal import available_removers, get_remover
from ..common.signal import bandpass
from ..hardware import config as HC
from . import analyses as A
from .metrics import baseline_sigma, run_block
from .report import COL_NAMES, METRICS, NpEncoder, build_tables, md_table, verdict, write_csvs, write_html
from .session import Block, load_session


def parse_channels(s, n):
    if not s:
        return list(range(n))
    out = []
    for part in s.split(","):
        if "-" in part:
            a, b = part.split("-")
            out += list(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return [c for c in out if c < n]


def example_traces(block, removers, sigma, out_png, params):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    pred = [p for p in block.pulses if p.get("kind") == "predictable"] or block.pulses
    if not pred:
        return None
    p = pred[len(pred) // 2]
    s0 = p["pulse_sample"]
    stim = block.channels_of(p["electrodes"])
    c_stim = stim[0]
    c_far = max(range(block.rec.n_channels), key=lambda c: min(abs(c - s) for s in stim))
    fs = block.rec.fs
    pulses = np.array(sorted(q["pulse_sample"] for q in block.pulses))
    fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
    for ax, c, what in ((axes[0], c_stim, "stimulated"), (axes[1], c_far, "far")):
        x = block.rec.channel(c)
        t = (np.arange(-int(0.002 * fs), int(0.045 * fs))) / fs * 1000
        for name in removers:
            try:
                r = get_remover(name).clean_channel(x, fs, pulses, **params.get(name, {}))
            except Exception:  # noqa: BLE001
                continue
            xf = bandpass(r.x, fs)[s0 + int(t[0] * fs / 1000): s0 + int(t[0] * fs / 1000) + len(t)]
            ax.plot(t[: len(xf)], xf / sigma[c], lw=0.8, label=COL_NAMES.get(name, name))
        ax.axhline(-5, color="k", ls="--", lw=0.6)
        ax.set_ylim(-40, 40)
        ax.set_ylabel(f"ch {c} ({what})\nnoise SDs")
    axes[0].legend(fontsize=7, ncol=3)
    axes[1].set_xlabel("ms after pulse (dashed = -5 SD spike threshold)")
    fig.suptitle(f"{block.name}: one pulse, band-passed 300-3000 Hz after each remover")
    fig.tight_layout()
    fig.savefig(out_png, dpi=110)
    plt.close(fig)
    return out_png


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--session", required=True)
    ap.add_argument("--removers", default=None)
    ap.add_argument("--channels", default=None)
    ap.add_argument("--episodes", default=None)
    ap.add_argument("--blank-ms", type=float, default=3.0)
    ap.add_argument("--salpa-halfwidth-ms", type=float, default=2.0)
    ap.add_argument("--si-mode", default="cubic")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)
    t_start = time.time()
    out = os.path.join(args.session, "benchmark")
    os.makedirs(out, exist_ok=True)
    session, names = load_session(args.session)
    avail = available_removers()
    want = args.removers.split(",") if args.removers else ["none", "salpa", "blank", "template", "spikeinterface"]
    removers = [r for r in want if avail.get(r) is True]
    if "salpa" in want and avail.get("salpa") is not True and "localpoly" not in removers:
        removers.append("localpoly")
        print("SALPA package not available -> using the pure-Python local-poly fallback column instead.")
    params = {"blank": {"blank_ms": args.blank_ms}, "salpa": {"halfwidth_ms": args.salpa_halfwidth_ms},
              "spikeinterface": {"mode": args.si_mode}}
    print(f"Session {args.session}: blocks {names}\nRemovers: {removers}")
    results, row_labels, full_labels, sections, extra = {}, {}, {}, [], {}

    # baseline -> noise per channel + health
    sigma = rate = None
    if "baseline" in names:
        b0 = Block(args.session, "baseline")
        sigma, rate = baseline_sigma(b0, b0.rec.n_channels)
        health = A.channel_health(b0)
        extra["channel_health"] = health
        bad = [h for h in health if h["status"] != "ok"]
        sections.append(f"<h2>Channel health (baseline, no stimulation)</h2><p>{60 - len(bad)} of {len(health)} channels look normal."
                        + (" Check: " + ", ".join(f"ch {h['channel']} ({h['status']})" for h in bad) if bad else "") + "</p>")

    # sweep -> electrode map (is stim electrode k == recording channel k?)
    emap = None
    e2c = None
    if "sweep" in names and sigma is not None:
        sw = Block(args.session, "sweep")
        emap = A.electrode_map(sw, sigma)
        extra["electrode_map"] = {k: v for k, v in emap.items() if k != "A"}
        np.save(os.path.join(out, "electrode_artifact_matrix.npy"), emap["A"])
        idf = emap["identity_fraction"]
        if idf < 0.9 and min(emap["confidence"]) > 1.3 and len(set(emap["best_channel"])) == len(emap["best_channel"]):
            e2c = emap["electrode_to_channel"]
        sections.append(f"<h2>Electrode map (sweep)</h2><p>Stimulating electrode k lit up recording channel k for "
                        f"{idf:.0%} of electrodes. " + ("This matches the game's assumption (LEFT_CHANNELS = electrodes 0-29)."
                        if idf >= 0.9 else "<b>It does NOT match: the game stimulates one set of electrodes and decodes a different set. "
                        "Using the measured map for the analysis.</b>") + "</p>")

    for name in names:
        if name not in HC.CONDITIONS:
            continue
        blk = Block(args.session, name, e2c)
        cond = HC.CONDITIONS[name]
        row_labels[name] = cond.get("short", name)
        full_labels[name] = cond["label"]
        if cond["layout"] == "few_inputs":
            L, R, bad = A.suggest_zones(emap, HC.LEFT, HC.RIGHT, blk.meta.get("few_inputs", HC.FEW_INPUTS)["left"],
                                        blk.meta.get("few_inputs", HC.FEW_INPUTS)["right"])
        else:
            L, R = np.array(HC.LEFT), np.array(HC.RIGHT)
        chans = parse_channels(args.channels, blk.rec.n_channels)
        print(f"  {name}: {len(blk.pulses)} pulses ({blk.pulse_source})")
        results[name] = run_block(blk, removers, sigma, rate, params, (L, R), args.seed, chans)
        results[name]["_pulse_source"] = blk.pulse_source
        print(f"    hardware blanking hold measured: {results[name]['_hold_ms']:.2f} ms")
        try:
            png = example_traces(blk, removers, sigma if sigma is not None else np.ones(60), os.path.join(out, f"example_traces_{name}.png"), params)
        except Exception as e:  # noqa: BLE001
            print("    (figure failed:", e, ")")

    if "amp_series" in names and sigma is not None:
        rows = A.amp_series(Block(args.session, "amp_series", e2c), sigma)
        extra["amp_series"] = rows
        sections.append("<h2>Amplitude series</h2><table><tr><th>pulse</th><th>amplitude (nA)</th><th>artifact peak (noise SDs)</th><th>blind period, no cleaning (ms)</th></tr>" +
                        "".join(f"<tr><td>{r['kind']}</td><td>{r['amplitude_nA']}</td><td>{r['artifact_peak_sd']:.0f}</td><td>{r['blind_ms_no_cleaning']:.1f}</td></tr>" for r in rows) + "</table>")
    if "switch" in names and sigma is not None:
        rows = A.switch_test(Block(args.session, "switch", e2c), sigma)
        extra["switch_test"] = rows
        sections.append("<h2>Generator switching test (Syrine's open question)</h2><p>reroute = one generator moved to the next electrode before every pulse; "
                        "alternate = two generators pre-wired, taking turns.</p><table><tr><th>test</th><th>target gap (ms)</th><th>pulses seen / commanded</th>"
                        "<th>achieved gap median (ms)</th><th>command time (ms)</th><th>right electrode, in order</th></tr>" +
                        "".join(f"<tr><td>{r['kind']}</td><td>{r['target_ms']:.0f}</td><td>{r['pulses_seen']}/{r['commanded']}</td><td>{r['achieved_gap_median_ms']:.1f}</td>"
                                f"<td>{r['command_ms_median']:.1f}</td><td>{r['right_electrode_in_order']:.0%}</td></tr>" for r in rows) + "</table>")
    if args.episodes and os.path.exists(args.episodes):
        ep = np.loadtxt(args.episodes, skiprows=1, ndmin=1)
        extra["saline_game"] = {"mean_steps": float(np.mean(ep)), "n": int(len(ep))}
        sections.insert(0, f"<h2>Game played on saline</h2><p>run_hardware.py on saline averaged <b>{np.mean(ep):.1f} steps</b> over {len(ep)} episodes "
                           f"(a random policy averages about 22). {'Clearly above random: the artifact is steering the game.' if np.mean(ep) > 30 else 'Close to random: no sign the artifact is steering the game.'}</p>")

    tables = build_tables(results, row_labels)
    write_csvs(tables, out)
    # one-sentence finding first (checkpoint style)
    best = {}
    for r in results:
        oks = [c for c in removers if isinstance(results[r].get(c), dict) and verdict(results[r].get(c))[0] == "PASS"]
        best[r] = oks
    finding = "; ".join(f"{row_labels[r]}: {', '.join(COL_NAMES[c] for c in v) if v else 'no remover passed'}" for r, v in best.items())
    sections.insert(0, f"<p><b>Finding:</b> removers that passed every check, per condition - {html_escape(finding)}.</p>"
                       "<p>Pulse timing source per block:</p><ul>" + "".join(f"<li>{r}: {html_escape(results[r]['_pulse_source'])}</li>" for r in results) + "</ul>")
    if session.get("dry_run"):
        sections.insert(0, "<p style='background:#f7c6c6;padding:10px;font-weight:bold'>FAKE DATA - this session came from the "
                           "simulated device (--dry-run). It only shows the code works; it says nothing about which remover is best.</p>")
    sections.append("<h2>Rows</h2><ul>" + "".join(f"<li><b>{html_escape(row_labels[r])}</b>: {html_escape(full_labels[r])}</li>" for r in results) +
                    "</ul><p>All rows use cathodic-first biphasic pulses. Rows R1-R3 and R5 have hardware blanking ON (as in mea_device.py), "
                    "so every SALPA cell there is 'hardware blanking + SALPA for the leftover'. The blind period (Syrine's 'measure the blind "
                    "period') is Tables 2-3, measured for every cell.</p>")
    write_html(tables, sections, out, f"Saline benchmark - {os.path.basename(os.path.abspath(args.session))}")
    with open(os.path.join(out, "report.md"), "w") as f:
        f.write(f"# Saline benchmark - {args.session}\n\n" + ("**FAKE DATA (dry run, simulated device) - code check only.**\n\n" if session.get("dry_run") else "") + f"**Finding:** {finding}\n\n")
        order = ["verdict"] + [k for k, *_ in METRICS]
        for i, k in enumerate(order, 1):
            t, cols, rows = tables[k]
            f.write(f"Table {i}. {t}\n\n{md_table(cols, rows)}\n\n")
    with open(os.path.join(out, "results.json"), "w") as f:
        json.dump({"results": results, "extra": extra, "removers": removers, "params": params}, f, indent=1, cls=NpEncoder)
    print(f"Done in {time.time() - t_start:.0f} s -> {out}/report.html")


def html_escape(s):
    import html as _h
    return _h.escape(s)


if __name__ == "__main__":
    main()
