"""
Check a session saved by the C# app ("2. Save raw data"):

    SpikeLayerApp.exe --save test_60s --seconds 60
    python tests/check_recording.py sessions/test_60s

Opens the file with load_recording() from Abbas's
Saline-Test/mea_kit/common/recording.py (branch Abbas-changes). That's the check:
if load_recording() opens it, the C# file is in the same format as recorder.py.
Then it checks length and sample rate and saves a plot next to the file
(<name>.png).

Exit code 0 = OK, 1 = a problem (printed).
"""
import argparse
import importlib.util
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RECORDING_PY = os.path.join("Saline-Test", "mea_kit", "common", "recording.py")


def find_recording_py(explicit):
    if explicit:
        return explicit
    d = HERE
    while True:
        p = os.path.join(d, RECORDING_PY)
        if os.path.exists(p):
            return p
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def load_mea_kit(path):
    spec = importlib.util.spec_from_file_location("mea_kit_recording", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("session", help="sessions/<name> (with or without .bin/.json)")
    ap.add_argument("--min-seconds", type=float, default=60.0, help="fail if shorter than this (default 60)")
    ap.add_argument("--recording-py", help="path to mea_kit/common/recording.py if it isn't found automatically")
    ap.add_argument("--no-plot", action="store_true")
    args = ap.parse_args()

    rp = find_recording_py(args.recording_py)
    if rp is None:
        print(f"Can't find {RECORDING_PY}. It's on the Abbas-changes branch. From the repo root run:\n"
              f"  git checkout origin/Abbas-changes -- Saline-Test/mea_kit\n"
              f"or pass --recording-py PATH.")
        return 1
    load_recording = load_mea_kit(rp).load_recording

    prefix = args.session
    for ext in (".json", ".bin"):
        if prefix.endswith(ext):
            prefix = prefix[: -len(ext)]

    problems = []
    rec = load_recording(prefix)          # <- the check from the task card
    with open(prefix + ".json") as f:
        meta = json.load(f)
    row_bytes = 4 * rec.n_streams
    bin_bytes = os.path.getsize(prefix + ".bin")

    scale = meta.get("uv_per_count")
    print(f"opened with           {rp}")
    print(f"sample rate           {rec.fs:.0f} Hz")
    print(f"channels              {rec.n_channels}")
    print(f"samples               {rec.n_samples:,}  ({rec.duration_s:.2f} s)")
    print(f"uV per AD count       {scale}" + ("  (FALLBACK, not confirmed)" if meta.get("uv_per_count_is_fallback") else ""))
    print(f"session closed        {meta.get('complete')}")

    if rec.fs != 50000:
        problems.append(f"sample rate is {rec.fs:.0f} Hz, expected 50000")
    if rec.n_channels != 60:
        problems.append(f"{rec.n_channels} channels, expected 60")
    if bin_bytes % row_bytes:
        problems.append(f".bin has {bin_bytes % row_bytes} extra bytes at the end (cut off mid-sample)")
    if not meta.get("complete"):
        problems.append(".json says the session wasn't closed (app crashed or was killed?); data up to that point is still readable")
    elif meta.get("n_samples") != rec.n_samples:
        problems.append(f".json says {meta.get('n_samples')} samples but the .bin has {rec.n_samples}")
    if rec.duration_s < args.min_seconds - 0.2:
        problems.append(f"only {rec.duration_s:.2f} s, expected at least {args.min_seconds:g} s")

    # per-channel stats (in uV if the file has a factor, else counts)
    unit = "uV" if scale else "counts"
    n10 = min(rec.n_samples, int(rec.fs * 10))
    rms = np.array([np.std(rec.channel(c, 0, n10)) for c in range(rec.n_channels)])
    flat = np.flatnonzero(rms == 0)
    print(f"RMS first 10 s        median {np.median(rms):.2f} {unit}, min {rms.min():.2f}, max {rms.max():.2f}")
    if len(flat):
        problems.append(f"flat (all-constant) channels: {flat.tolist()}")

    if not args.no_plot:
        png = plot(rec, rms, unit, prefix)
        print(f"plot                  {png}")

    if problems:
        print("\nPROBLEMS:")
        for p in problems:
            print("  - " + p)
        return 1
    print("\nOK: the file opens with load_recording() and is the right length.")
    return 0


def plot(rec, rms, unit, prefix):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ink, muted = "#1f2933", "#7b8794"
    fig, axes = plt.subplots(3, 1, figsize=(11, 10), gridspec_kw={"height_ratios": [3, 1.4, 1.4]})

    # 1. 200 ms of 8 electrodes, stacked
    ax = axes[0]
    chans = [0, 8, 16, 24, 32, 40, 48, 56]
    n = min(rec.n_samples, int(rec.fs * 0.2))
    t = np.arange(n) / rec.fs * 1000
    gap = 8 * max(np.median(rms), 1e-9)
    for i, c in enumerate(chans):
        x = rec.channel(c, 0, n)
        ax.plot(t, x - x.mean() - i * gap, color=ink, lw=0.6)
        ax.text(t[-1] * 1.01, -i * gap, f"ch {c}", va="center", fontsize=8, color=muted)
    ax.set_yticks([])
    ax.set_xlabel("ms")
    ax.set_title("First 200 ms, 8 electrodes (mean removed, stacked)", loc="left", fontsize=10)

    # 2. channel 0 over the whole file (min/max per 10 ms, so nothing is hidden)
    ax = axes[1]
    step = int(rec.fs / 100)
    x = rec.channel(0)
    m = len(x) // step
    blocks = x[: m * step].reshape(m, step)
    tt = np.arange(m) * step / rec.fs
    ax.fill_between(tt, blocks.min(1), blocks.max(1), color=ink, lw=0)
    ax.set_xlabel("s")
    ax.set_ylabel(unit)
    ax.set_title(f"Channel 0, whole recording ({rec.duration_s:.1f} s, min/max per 10 ms): gaps or jumps show up here",
                 loc="left", fontsize=10)

    # 3. RMS per channel
    ax = axes[2]
    ax.bar(np.arange(len(rms)), rms, color=ink, width=0.7)
    ax.set_xlabel("channel")
    ax.set_ylabel(f"RMS ({unit})")
    ax.set_title("RMS per channel, first 10 s (raw, not filtered)", loc="left", fontsize=10)

    for ax in axes:
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        ax.tick_params(colors=muted, labelsize=8)
    fig.tight_layout()
    png = prefix + ".png"
    fig.savefig(png, dpi=110)
    plt.close(fig)
    return png


if __name__ == "__main__":
    sys.exit(main())
