"""UT-11 and UT-14: folklore provenance and seven-ecosystem comparison."""

from __future__ import annotations

from pathlib import Path

from fs_stride_analysis.folklore import compare, load_folklore

ROOT = Path(__file__).resolve().parents[2]
ECOSYSTEMS = {
    "crossbeam_utils",
    "folly",
    "hotspot_jvm",
    "go_runtime",
    "linux_kernel",
    "cpp17_hardware_destructive_interference_size",
    "cpython_qsbr",
}


def test_ut11_every_entry_has_provenance():
    data = load_folklore(ROOT / "data" / "folklore.toml")
    assert set(data) == ECOSYSTEMS
    for name, entry in data.items():
        assert entry.get("url"), name
        assert entry.get("version") or entry.get("commit"), name
        assert entry.get("retrieval_date"), name
        assert entry.get("x86_64_bytes"), name


def test_compare_joins_all_seven_ecosystems():
    folklore = load_folklore(ROOT / "data" / "folklore.toml")
    configs = [
        {
            "mode": "atomic",
            "threads": 4,
            "placement": "cores",
            "primary": True,
            "knee_bytes": 64,
        }
    ]
    rows = compare(configs, folklore, "x86_64")
    assert {r["ecosystem"] for r in rows} == ECOSYSTEMS
    by_eco = {r["ecosystem"]: r for r in rows}
    assert by_eco["go_runtime"]["agree"] is True
    assert by_eco["crossbeam_utils"]["agree"] is False
    assert by_eco["linux_kernel"]["agree"] is True


def test_compare_handles_unknown_knee():
    folklore = load_folklore(ROOT / "data" / "folklore.toml")
    configs = [
        {
            "mode": "atomic",
            "threads": 4,
            "placement": "cores",
            "primary": True,
            "knee_bytes": None,
        }
    ]
    rows = compare(configs, folklore, "aarch64")
    assert all(r["agree"] is None for r in rows)
