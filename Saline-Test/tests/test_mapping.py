"""Abbas, Oct 21 2026: v2 finds known connections; v1 over-reports; v3 + drift run."""
import numpy as np

from mea_kit.ucsc_mapping import drift, synthetic, v1_ucsc_faithful as v1, v2_ours_adapted as v2, v3_auto_select as v3


def _found(r):
    W = r["chosen_window_ms"]
    res = r[f"W{int(W)}"]
    return {(r["stims"][a], r["units"][b]) for a, b in zip(*np.nonzero(res["significant"]))}


def test_v2_recovers_true_pairs():
    cul = synthetic.make_culture(seed=3)
    r = v2.run(cul["spont"], cul["sweep"], cleaner="template", blind_ms=1.5)
    found = _found(r)
    true = set(cul["true_pairs"])
    assert len(found & true) >= 0.8 * len(true)
    assert len(found - true) <= 2
    assert cul["bursty"] in r["bursty_inputs"]


def test_v1_overreports_and_v3_drift():
    cul = synthetic.make_culture(seed=4)
    r1 = v1.run(cul["spont"], cul["sweep"])
    C = np.nan_to_num(r1["C1_10ms"])
    assert (C > 0.3).sum() > len(cul["true_pairs"])          # artifact/noise -> fake connections
    r2 = v2.run(cul["spont"], cul["sweep"], cleaner="template", blind_ms=1.5)
    r3 = v3.run(r2, zones="learned", k=2)
    assert r3["best"] is not None
    d = drift.compare(r2, r2, r2)
    assert d["n_changed_beyond_drift"] == 0
