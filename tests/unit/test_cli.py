"""NT-01 to NT-03 and CLI exit-code contract."""

from __future__ import annotations

import json
import logging

from fs_stride_analysis.cli import analyze_run, main
from fs_stride_analysis.io import load_raw


def test_nt01_missing_raw_data(tmp_path, capsys):
    assert analyze_run(tmp_path) == 1
    assert "run fs_stride first" in capsys.readouterr().err


def test_nt02_missing_column_names_it(make_run, capsys):
    run_dir = make_run(drop_col="mode")
    try:
        load_raw(run_dir / "raw.csv")
    except ValueError as exc:
        assert "missing column: mode" in str(exc)
    else:
        raise AssertionError("expected ValueError for a missing column")

    # A schema error is not an affinity failure, so the CLI must exit 1.
    assert analyze_run(run_dir) == 1
    assert "missing column: mode" in capsys.readouterr().err


def test_nt03_single_thread_has_no_knee(make_run, caplog):
    run_dir = make_run(threads=1)
    with caplog.at_level(logging.WARNING, logger="fs_stride_analysis.classify"):
        assert analyze_run(run_dir) == 0
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["configs"][0]["knee_bytes"] is None
    assert "threads=1 only" in caplog.text


def test_cli_bad_argument_exits_2():
    assert main(["bogus"]) == 2
    assert main(["analyze"]) == 2


def test_cli_sim_exit_code():
    assert main(["sim"]) == 0
