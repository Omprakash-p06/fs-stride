"""Shared fixtures for fs-stride analysis unit tests."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

RAW_COLS = (
    "run_id",
    "host",
    "mode",
    "stride",
    "threads",
    "placement",
    "block",
    "order",
    "role",
    "total_ops",
    "elapsed_s",
    "ns_per_op",
    "cpus",
    "loadavg1",
)

DEFAULT_NS = {
    8: 200.0,
    16: 180.0,
    32: 170.0,
    64: 160.0,
    128: 100.0,
    256: 100.0,
    512: 100.0,
}


def meta_dict() -> dict:
    """Return a schema-valid meta.json payload."""
    return {
        "schema_version": "2.0",
        "cpu_model": "Test CPU",
        "microarch": "test",
        "arch": "x86_64",
        "lscpu": "test",
        "kernel": "6.0.0",
        "governor": "performance",
        "smt": "on",
        "p_core_cpus": "0-3",
        "e_core_cpus": "unknown",
        "sysfs_coherency_line_size": 64,
        "hypervisor": "none",
        "loadavg_start": "0.10",
        "compiler": "gcc 14.4",
        "cflags": "-O2",
        "atomic_opcode": "lock addq",
        "omp_runtime": "libgomp",
        "omp_num_threads": "2",
        "omp_proc_bind": "unset",
        "omp_places": "unset",
        "git_sha": "abc1234",
        "seed": 42,
        "shared_host": False,
        "warnings": [],
    }


def _write_raw(
    path: Path, rows: list[dict], drop_col: str | None, extra_col: bool
) -> None:
    cols = [c for c in RAW_COLS if c != drop_col]
    if extra_col:
        cols = [*cols, "surprise"]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=cols)
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c, 1) for c in cols})


@pytest.fixture
def base_meta() -> dict:
    """Return a fresh schema-valid meta.json payload."""
    return meta_dict()


@pytest.fixture
def make_run(tmp_path):
    """Create a synthetic results/<RUN> directory with raw.csv and meta.json."""

    def _make(
        name: str = "run",
        threads: int = 2,
        strides: tuple[int, ...] = (8, 16, 32, 64, 128, 256, 512),
        blocks: int = 5,
        ns: dict[int, float] | None = None,
        drop_col: str | None = None,
        extra_col: bool = False,
        meta: dict | None = None,
    ) -> Path:
        run_dir = tmp_path / name
        run_dir.mkdir()
        values = {**DEFAULT_NS, **(ns or {})}
        rows: list[dict] = []
        order = 0
        for block in range(blocks + 1):
            for stride in strides:
                role = "ref" if stride == 256 else "test"
                nsv = values[stride]
                elapsed = nsv * 100_000 / (1e9 * threads)
                rows.append(
                    {
                        "run_id": "test-host-1",
                        "host": "testhost",
                        "mode": "atomic",
                        "stride": stride,
                        "threads": threads,
                        "placement": "cores",
                        "block": block,
                        "order": order,
                        "role": role,
                        "total_ops": 100_000,
                        "elapsed_s": elapsed,
                        "ns_per_op": nsv,
                        "cpus": "0;2",
                        "loadavg1": 0.1,
                    }
                )
                order += 1
            nsv = values[256]
            rows.append(
                {
                    "run_id": "test-host-1",
                    "host": "testhost",
                    "mode": "atomic",
                    "stride": 256,
                    "threads": threads,
                    "placement": "cores",
                    "block": block,
                    "order": order,
                    "role": "sentinel",
                    "total_ops": 100_000,
                    "elapsed_s": nsv * 100_000 / (1e9 * threads),
                    "ns_per_op": nsv,
                    "cpus": "0;2",
                    "loadavg1": 0.1,
                }
            )
            order += 1
        _write_raw(run_dir / "raw.csv", rows, drop_col, extra_col)
        (run_dir / "meta.json").write_text(
            json.dumps(meta or meta_dict(), indent=2) + "\n", encoding="utf-8"
        )
        return run_dir

    return _make
