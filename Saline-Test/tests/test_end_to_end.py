"""Abbas, Oct 21 2026: dry-run protocol -> exact pulse times -> benchmark -> report files."""
import json
import os

import numpy as np
import pytest

from mea_kit.hardware import saline_protocol
from mea_kit.saline_benchmark import run_benchmark
from mea_kit.saline_benchmark.session import Block


@pytest.fixture(scope="module")
def session(tmp_path_factory):
    out = str(tmp_path_factory.mktemp("dry"))
    saline_protocol.main(["--dry-run", "--out", out, "--blocks", "baseline,R1_normal,R3_short,R5_moved_zones,switch",
                          "--game-windows", "40", "--baseline-s", "4"])
    return out


def test_pulses_exact_from_sideband(session):
    b = Block(session, "R1_normal")
    true = np.array(sorted(b.meta["true_pulse_samples"]))
    got = np.array(sorted(p["pulse_sample"] for p in b.pulses))
    assert "sideband" in b.pulse_source
    assert len(got) >= 0.95 * len(true)
    assert np.all(np.min(np.abs(got[:, None] - true[None, :]), axis=1) == 0)


def test_pulses_without_sideband(session):
    b = Block(session, "R1_normal")
    b.rec.n_streams = 60            # pretend the sideband was not recorded
    from mea_kit.common.pulses import refine_from_commands
    rows, why = refine_from_commands(b.rec, b.commands)
    assert why.startswith("artifact")
    true = np.array(sorted(b.meta["true_pulse_samples"]))
    got = np.array(sorted(r["pulse_sample"] for r in rows))
    err = np.min(np.abs(got[:, None] - true[None, :]), axis=1)
    assert np.median(err) <= 2 and np.mean(err <= int(0.0005 * b.rec.fs)) > 0.8


def test_benchmark_runs(session):
    run_benchmark.main(["--session", session, "--channels", "0-3,26-33,56-59", "--removers", "none,blank,template,salpa"])
    out = os.path.join(session, "benchmark")
    for f in ("report.html", "report.md", "results.json", "pivot_verdict.csv"):
        assert os.path.exists(os.path.join(out, f))
    res = json.load(open(os.path.join(out, "results.json")))["results"]
    # with no cleaning the fake artifact steers the decoder; cleaning should cut false spikes
    assert res["R1_normal"]["none"]["decoder_follow_rate"] > 0.8
    assert res["R1_normal"]["blank"]["false_other_per100"] < res["R1_normal"]["none"]["false_other_per100"]
