"""
Pivot tables + report. Abbas, Oct 21 2026 (new).

Rows = stimulation strategies (pivot rows from the plan), columns = artifact removers.
One table per metric, plus a verdict table. Written as CSV, Markdown and a colour-coded HTML page.
Report follows the Neurotech checkpoint style: one-sentence finding first, then the numbers.
"""
import html
import json
import os

import numpy as np

METRICS = [
    ("blind_stim_median_ms", "Blind period on STIMULATED electrodes (median ms) - lower is better", "{:.1f}", "low"),
    ("blind_other_median_ms", "Blind period on OTHER electrodes (median ms) - lower is better", "{:.1f}", "low"),
    ("false_other_per100", "False spikes per 100 pulses per channel (other electrodes) - ~0 is right", "{:.1f}", "low"),
    ("recall_other_2-10ms", "Injected spikes recovered 2-10 ms after a pulse (other electrodes, %) - higher is better", "{:.0%}", "high"),
    ("recall_stim_2-10ms", "Injected spikes recovered 2-10 ms after a pulse (stimulated electrodes, %)", "{:.0%}", "high"),
    ("decoder_follow_rate", "Game decoder picks the STIMULATED side (%) - 50% is right on saline (decoder ignores blanked samples)", "{:.0%}", "half"),
    ("decoder_asis_follow_rate", "Same, with today's count_spikes unchanged (counts blanked samples too)", "{:.0%}", "half"),
]

COL_ORDER = ["none", "salpa", "blank", "template", "spikeinterface", "localpoly"]
COL_NAMES = {"none": "No cleaning", "salpa": "SALPA", "blank": "Simple blanking", "template": "Template subtraction",
             "spikeinterface": "SpikeInterface", "localpoly": "Local-poly (SALPA-like fallback)"}


def verdict(s):
    if not s or "error" in s:
        return "n/a", []
    probs = []
    ci = s.get("decoder_follow_ci")
    if ci is not None and np.isfinite(ci[0]) and not (ci[0] <= 0.5 <= ci[1]):
        probs.append("decoder biased")
    r = s.get("recall_other_2-10ms", np.nan)
    if np.isfinite(r) and r < 0.7:
        probs.append("loses spikes")
    f = s.get("false_other_per100", np.nan)
    if np.isfinite(f) and f > 5:
        probs.append("false spikes")
    b = s.get("blind_stim_median_ms", np.nan)
    if np.isfinite(b) and b > 5:
        probs.append("long blind period")
    if not probs:
        return "PASS", probs
    return ("FAIL" if ("decoder biased" in probs or len(probs) >= 2) else "CHECK"), probs


def _fmt(v, fmt):
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "-"
    return fmt.format(v)


def build_tables(results, row_labels):
    cols = [c for c in COL_ORDER if any(c in results[r] for r in results)]
    results = {r: {k: v for k, v in d.items() if not k.startswith('_')} for r, d in results.items()}
    tables = {}
    for key, title, fmt, _ in METRICS:
        t = []
        for r in results:
            t.append([row_labels.get(r, r)] + [_fmt(results[r].get(c, {}).get(key), fmt) if "error" not in results[r].get(c, {}) else "n/a" for c in cols])
        tables[key] = (title, cols, t)
    vt = []
    for r in results:
        vt.append([row_labels.get(r, r)] + [verdict(results[r].get(c))[0] + ("" if not verdict(results[r].get(c))[1] else " (" + ", ".join(verdict(results[r].get(c))[1]) + ")") for c in cols])
    tables["verdict"] = ("Verdict per cell (PASS / CHECK / FAIL)", cols, vt)
    return tables


def write_csvs(tables, out):
    import csv
    for key, (title, cols, rows) in tables.items():
        with open(os.path.join(out, f"pivot_{key.replace('-', '_')}.csv"), "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["Condition"] + [COL_NAMES.get(c, c) for c in cols])
            w.writerows(rows)


def md_table(cols, rows):
    head = "| Condition | " + " | ".join(COL_NAMES.get(c, c) for c in cols) + " |"
    sep = "|" + "---|" * (len(cols) + 1)
    return "\n".join([head, sep] + ["| " + " | ".join(map(str, r)) + " |" for r in rows])


def _cell_color(key, text):
    if text in ("-", "n/a"):
        return "#eeeeee"
    if key == "verdict":
        return {"PASS": "#c8f0c8", "CHECK": "#fff2b3", "FAIL": "#f7c6c6"}.get(text.split(" ")[0], "#eeeeee")
    try:
        v = float(text.strip("%")) / (100 if text.endswith("%") else 1)
    except ValueError:
        return "#ffffff"
    kind = {k: d for k, _, _, d in METRICS}[key]
    if kind == "low":
        good, bad = (2, 6) if "blind" in key else (1, 5)
        return "#c8f0c8" if v <= good else ("#fff2b3" if v <= bad else "#f7c6c6")
    if kind == "high":
        return "#c8f0c8" if v >= 0.85 else ("#fff2b3" if v >= 0.6 else "#f7c6c6")
    if kind == "half":
        return "#c8f0c8" if abs(v - 0.5) <= 0.1 else ("#fff2b3" if abs(v - 0.5) <= 0.2 else "#f7c6c6")
    return "#ffffff"


def write_html(tables, sections, out, title):
    parts = [f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title>",
             "<style>body{font-family:system-ui,Arial,sans-serif;max-width:1200px;margin:24px auto;padding:0 16px;color:#222}"
             "table{border-collapse:collapse;margin:8px 0 24px}td,th{border:1px solid #ccc;padding:5px 8px;font-size:13px;text-align:center}"
             "td:first-child,th:first-child{text-align:left;max-width:380px}h2{margin-top:32px}pre{background:#f6f6f6;padding:8px;overflow-x:auto}</style></head><body>",
             f"<h1>{html.escape(title)}</h1>"]
    for s in sections:
        parts.append(s)
    order = ["verdict"] + [k for k, *_ in METRICS]
    for i, key in enumerate(order, 1):
        t, cols, rows = tables[key]
        parts.append(f"<h2>Table {i}. {html.escape(t)}</h2><table><tr><th>Condition</th>" +
                     "".join(f"<th>{html.escape(COL_NAMES.get(c, c))}</th>" for c in cols) + "</tr>")
        for r in rows:
            parts.append("<tr><td>" + html.escape(str(r[0])) + "</td>" +
                         "".join(f"<td style='background:{_cell_color(key, str(v))}'>{html.escape(str(v))}</td>" for v in r[1:]) + "</tr>")
        parts.append("</table>")
    parts.append("</body></html>")
    with open(os.path.join(out, "report.html"), "w") as f:
        f.write("\n".join(parts))


class NpEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating,)):
            return float(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
        if isinstance(o, tuple):
            return list(o)
        return super().default(o)
