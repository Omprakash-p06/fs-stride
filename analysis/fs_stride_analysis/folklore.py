"""External padding-folklore loader and measured-knee comparison."""

from __future__ import annotations

import tomllib
from pathlib import Path


def load_folklore(path: Path) -> dict:
    """Parse data/folklore.toml via stdlib tomllib."""
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _norm_arch(arch: str) -> str:
    a = arch.lower()
    if a in {"x86_64", "amd64", "x86-64"}:
        return "x86_64"
    if a in {"aarch64", "arm64"}:
        return "aarch64"
    if a == "s390x":
        return "s390x"
    return "x86_64"


def _matches_folklore(measured: int | None, expected: int | str) -> bool | None:
    if measured is None:
        return None
    if isinstance(expected, int):
        return measured == expected
    if isinstance(expected, str) and "-" in expected:
        lo, hi = (int(x.strip()) for x in expected.split("-", 1))
        return lo <= measured <= hi
    return None


def compare(configs: list[dict], folklore: dict, arch: str) -> list[dict]:
    """Join measured knees against all 7 ecosystems for target architecture."""
    norm = _norm_arch(arch)
    targets = (
        [c for c in configs if c["primary"]]
        or [c for c in configs if c["mode"] in {"atomic", "coupled-pair"}]
        or configs[:1]
    )
    rows: list[dict] = []
    for cfg in targets:
        for eco, entry in folklore.items():
            fbytes = entry.get(f"{norm}_bytes", entry.get("x86_64_bytes", "unknown"))
            rows.append(
                {
                    "ecosystem": eco,
                    "arch": norm,
                    "mode": cfg["mode"],
                    "threads": cfg["threads"],
                    "placement": cfg["placement"],
                    "measured_knee_bytes": cfg["knee_bytes"],
                    "folklore_bytes": fbytes,
                    "agree": _matches_folklore(cfg["knee_bytes"], fbytes),
                }
            )
    return rows
