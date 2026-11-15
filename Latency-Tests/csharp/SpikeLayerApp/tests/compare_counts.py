"""
Check the C# spike counter against Python on the same saved file ("3. Detect spikes").

    dotnet run --project tests -- sessions/NAME   # C# counts -> sessions/NAME_counts_csharp.csv
    python tests/compare_counts.py sessions/NAME       # Python counts the same windows, compares

count_window() below is the Python copy of SpikeCounter.CountChannel in C#,
built from scipy (butter + sosfilt). Same method:
  - 10 ms extra on each side of the window (filter edge swing lands there, not in the count)
  - each pulse until 2 ms after it is masked: bridged with a straight line
    before filtering, and never counted
  - band-pass 300-3000 Hz, forwards then backwards
  - sigma = median(|filtered|) / 0.6745 over the unmasked window
  - count downward crossings of -5 sigma, at least 1 ms apart

Exit code 0 = every count matches, 1 = mismatches (listed).
"""
import argparse
import json
import sys

import numpy as np
from scipy.signal import butter, sosfilt

THRESHOLD_SD = 5.0
MARGIN_MS = 10
REFRACTORY_MS = 1
MASK_AFTER_US = 2000
BAND_HZ = (300.0, 3000.0)
GRID_MS = 100


def sos_for(fs):
    return butter(2, list(BAND_HZ), btype="bandpass", fs=fs, output="sos")


def us_to_samples(us, fs):
    return us * int(fs) // 1_000_000


def pulse_mask(left, right, n, fs, mask_after_us=MASK_AFTER_US):
    """Same as WaveRules.SpikeMask: each nonzero piece, from its start until mask_after_us after its end."""
    mask = np.zeros(n, bool)
    for wave in (left, right):
        t = 0
        for amp, length in wave:
            if amp != 0:
                a = max(0, us_to_samples(t, fs))
                b = min(n, us_to_samples(t + length + mask_after_us, fs))
                mask[a:b] = True
            t += length
    return mask


def count_window(x, margin, n, mask, fs, sos):
    """x: one electrode, uV, window plus `margin` samples each side. Returns (count, sigma)."""
    x = np.array(x, dtype=np.float64)

    # bridge masked stretches with a straight line
    k = 0
    while k < n:
        if not mask[k]:
            k += 1
            continue
        end = k
        while end < n and mask[end]:
            end += 1
        a, b = x[margin + k - 1], x[margin + end]
        j = np.arange(k, end)
        x[margin + j] = a + (b - a) * (j - k + 1) / (end - k + 1)
        k = end

    y = x - x.mean()
    y = sosfilt(sos, y)                 # forwards, starting from rest (same as C#)
    y = sosfilt(sos, y[::-1])[::-1]     # backwards

    mid = y[margin:margin + n]
    unmasked = np.abs(mid[~mask])
    if unmasked.size == 0:
        return 0, 0.0
    sigma = np.median(unmasked) / 0.6745
    if sigma <= 0:
        return 0, sigma
    thr = -THRESHOLD_SD * sigma

    refractory = int(fs) * REFRACTORY_MS // 1000
    below = mid < thr
    prev = y[margin - 1] < thr
    count, last = 0, -10**9
    for k in np.flatnonzero(below & ~np.concatenate(([prev], below[:-1])) & ~mask):
        if k - last >= refractory:
            count += 1
            last = k
    return count, sigma


def windows_for(meta, fs, total, grid):
    wins = [] if grid else [w for w in meta.get("windows", []) if w.get("n_samples", 0) > 0]
    if wins:
        return [(w["window"], w["first_sample"], w["n_samples"], w["left"], w["right"]) for w in wins]
    n = int(fs) * GRID_MS // 1000
    return [(s // n, s, n, [], []) for s in range(0, total - n + 1, n)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("session", help="sessions/<name>")
    ap.add_argument("--grid", action="store_true", help="100 ms grid even if the session logged windows (must match the C# run)")
    args = ap.parse_args()
    prefix = args.session
    for ext in (".json", ".bin"):
        if prefix.endswith(ext):
            prefix = prefix[: -len(ext)]

    meta = json.load(open(prefix + ".json"))
    fs, streams, uv = meta["fs"], meta["n_streams"], meta["uv_per_count"]
    raw = np.memmap(prefix + ".bin", dtype="<i4", mode="r")
    total = raw.size // streams
    raw = raw[: total * streams].reshape(total, streams)
    margin = int(fs) * MARGIN_MS // 1000
    sos = sos_for(fs)

    cs = np.genfromtxt(prefix + "_counts_csharp.csv", delimiter=",", names=True)
    cs = np.atleast_1d(cs)
    cs_by_first = {int(r["first_sample"]): r for r in cs}

    mismatches, checked, sig_err = [], 0, 0.0
    for wid, first, n, left, right in windows_for(meta, fs, total, args.grid):
        if first - margin < 0 or first + n + margin > total:
            continue
        if first not in cs_by_first:
            mismatches.append(f"window {wid}: missing from the C# csv")
            continue
        row = cs_by_first[first]
        mask = pulse_mask(left, right, n, fs)
        block = raw[first - margin: first + n + margin].astype(np.float64) * uv
        for c in range(streams):
            count, sigma = count_window(block[:, c], margin, n, mask, fs, sos)
            c_count, c_sigma = int(row[f"count_{c}"]), float(row[f"noise_uv_{c}"])
            if count != c_count:
                mismatches.append(f"window {wid} electrode {c}: Python {count}, C# {c_count}")
            if sigma > 0:
                sig_err = max(sig_err, abs(sigma - c_sigma) / sigma)
        checked += 1

    print(f"windows compared      {checked} (C# csv has {len(cs)})")
    print(f"electrode-windows     {checked * streams:,}")
    print(f"total spikes, C#      {int(sum(cs[f'count_{c}'].sum() for c in range(streams))):,}")
    print(f"worst sigma diff      {sig_err:.2e} (relative)")
    if checked == 0:
        print("\nNothing compared. Is the C# csv from the same file and the same --grid setting?")
        return 1
    if mismatches:
        print(f"\nMISMATCHES: {len(mismatches)}")
        for m in mismatches[:30]:
            print("  " + m)
        if len(mismatches) > 30:
            print(f"  ... and {len(mismatches) - 30} more")
        return 1
    print("\nOK: every count matches.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
