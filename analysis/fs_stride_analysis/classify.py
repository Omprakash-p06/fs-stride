"""Cache-line knee estimator and configuration classifier."""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)
CANONICAL_GRID = (8, 16, 32, 64, 128, 256, 512, 1024)


def is_primary_config(mode: str, threads: int, max_threads: int, placement: str) -> bool:
    """Return True iff config belongs to the primary confirmatory family."""
    return (
        mode in {"atomic", "coupled-pair"}
        and placement in {"cores", "spread"}
        and threads == max_threads
        and threads >= 2
    )


def knee(contended: dict[int, bool]) -> tuple[int | None, str]:
    """Return smallest uncontended s* such that all s >= s* are uncontended."""
    if not contended or not any(contended.values()):
        return None, "flat"
    seen_false = False
    for s in sorted(contended):
        if contended[s]:
            if seen_false:
                return None, "irregular"
        else:
            seen_false = True
    last_true = max(s for s, flag in contended.items() if flag)
    s_star = next((g for g in CANONICAL_GRID if g > last_true), last_true * 2)
    if s_star <= 64:
        return s_star, "line64"
    if s_star == 128:
        return 128, "pair128"
    return s_star, "wider"


def classify_config(summary: dict, gate: float = 0.10) -> tuple[str, int | None, str, str | None]:
    """Classify one config using MDE90 gate, faster-wider check, and knee rule."""
    mde_val = float(summary["mde90"])
    if mde_val > gate:
        return (
            "inconclusive",
            None,
            "inconclusive",
            f"sentinel mde90={mde_val * 100:.2f}% > {gate * 100:.1f}%",
        )
    for cell in summary.get("faster_wider", []):
        stride = int(cell["stride"])
        log.warning("faster-wider detected at stride %d; not a knee", stride)
        return "irregular", None, "pass", f"faster-wider at stride {stride}"
    contended_map = {int(s): bool(v) for s, v in summary["contended"].items()}
    k_bytes, cls = knee(contended_map)
    if summary.get("single_thread"):
        log.warning("threads=1 only; no knee reported")
        return cls, None, "pass", "single-thread baseline only"
    return cls, k_bytes, "pass", None
