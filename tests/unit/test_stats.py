"""UT-06 to UT-09: CSV contract, paired t-test, Holm, and MDE90."""

from __future__ import annotations

import csv

import numpy as np
import pytest
from fs_stride_analysis.io import RAW_COLS, load_raw
from fs_stride_analysis.stats import ALPHA_FW, M_PRIMARY, holm, mde90, paired_t
from scipy.stats import t as student_t
from scipy.stats import ttest_rel


def test_ut06_exact_columns_and_ns_formula(make_run):
    run_dir = make_run(blocks=3)
    with (run_dir / "raw.csv").open(newline="", encoding="utf-8") as fh:
        assert next(csv.reader(fh)) == list(RAW_COLS)

    rows = load_raw(run_dir / "raw.csv")
    assert tuple(rows[0]) == RAW_COLS
    assert {r["block"] for r in rows} == {1, 2, 3}
    assert len(rows) == 3 * (7 + 1)
    for row in rows:
        expected = row["elapsed_s"] * 1e9 * row["threads"] / row["total_ops"]
        assert row["ns_per_op"] == pytest.approx(expected, abs=1e-6)


def test_ut06_rejects_missing_and_extra_columns(make_run):
    with pytest.raises(ValueError, match="missing column: mode"):
        load_raw(make_run(name="missing", drop_col="mode") / "raw.csv")
    with pytest.raises(ValueError, match="unexpected column: surprise"):
        load_raw(make_run(name="extra", extra_col=True) / "raw.csv")


def test_ut07_paired_t_matches_scipy():
    a = np.array([1.10, 1.04, 1.22, 0.97, 1.15, 1.01, 1.09, 1.13])
    b = np.array([1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00])
    mean, sd, t_stat, p_val = paired_t(a - b)
    ref = ttest_rel(a, b)
    assert mean == pytest.approx(float(np.mean(a - b)))
    assert sd == pytest.approx(float(np.std(a - b, ddof=1)))
    assert t_stat == pytest.approx(ref.statistic)
    assert p_val == pytest.approx(ref.pvalue / 2.0)


def test_ut08_holm_hand_computed():
    # Sorted raw p: 0.005, 0.010, 0.030, 0.040 at m = 4.
    raw = [0.010, 0.040, 0.030, 0.005]
    assert holm(raw) == pytest.approx([0.030, 0.060, 0.060, 0.020])
    assert holm([]) == []
    assert holm([0.5]) == pytest.approx([0.5])


def test_ut09_mde90_worked_example():
    sd, blocks = 0.02, 30
    t_crit = student_t.ppf(1.0 - ALPHA_FW / M_PRIMARY, df=blocks - 1)
    t_pow = student_t.ppf(0.90, df=blocks - 1)
    expected = float(np.exp((t_crit + t_pow) * sd / np.sqrt(blocks)) - 1.0)
    assert mde90(sd, blocks) == pytest.approx(expected)
    assert mde90(0.0, blocks) == 0.0
    assert mde90(sd, 1) == 0.0
