"""UT-12 and UT-13: meta.json and summary.json schema validation."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
from fs_stride_analysis.cli import analyze_run
from fs_stride_analysis.io import load_meta

ROOT = Path(__file__).resolve().parents[2]
FR09_KEYS = {
    "schema_version",
    "cpu_model",
    "microarch",
    "arch",
    "lscpu",
    "kernel",
    "governor",
    "smt",
    "p_core_cpus",
    "e_core_cpus",
    "sysfs_coherency_line_size",
    "hypervisor",
    "loadavg_start",
    "compiler",
    "cflags",
    "atomic_opcode",
    "omp_runtime",
    "omp_num_threads",
    "omp_proc_bind",
    "omp_places",
    "git_sha",
    "seed",
    "shared_host",
    "warnings",
}


def _schema(name: str) -> dict:
    return json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))


def test_ut12_meta_validates_against_schema(make_run):
    run_dir = make_run()
    meta = load_meta(run_dir / "meta.json")
    jsonschema.validate(meta, _schema("meta.schema.json"))


def test_ut12_schema_covers_fr09_keys():
    schema = _schema("meta.schema.json")
    assert set(schema["required"]) == FR09_KEYS
    assert set(schema["properties"]) == FR09_KEYS


def test_ut12_rejects_wrong_schema_version(make_run, base_meta):
    run_dir = make_run(meta={**base_meta, "schema_version": "1.0"})
    try:
        load_meta(run_dir / "meta.json")
    except ValueError as exc:
        assert "schema_version" in str(exc)
    else:
        raise AssertionError("expected ValueError for schema_version 1.0")


def test_ut13_summary_validates_against_schema(make_run):
    run_dir = make_run()
    assert analyze_run(run_dir) == 0
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    jsonschema.validate(summary, _schema("summary.schema.json"))
    assert summary["alpha_fw"] == 0.01
    assert summary["m_primary"] == 5
    assert summary["n_blocks"] == 5
