"""Within-block paired log-ratio statistics and multiplicity control."""

from __future__ import annotations

import numpy as np
from scipy.stats import t as student_t

PRIMARY_STRIDES = (8, 16, 32, 64, 128)
REF_STRIDE = 256
ALPHA_FW = 0.01
M_PRIMARY = 5
EFFECT_FLOOR = 0.01


def log_ratios(rows: list[dict], config: tuple[str, int, str]) -> tuple[dict[int, np.ndarray], np.ndarray]:
    """Compute within-block paired log ratios ln(y_s,b / y_256,b) and sentinel ratios."""
    mode, threads, placement = config
    by_blk: dict[int, dict[tuple[int, str], float]] = {}
    strides: set[int] = set()
    for r in rows:
        if r["mode"] == mode and r["threads"] == threads and r["placement"] == placement:
            by_blk.setdefault(r["block"], {})[(r["stride"], r["role"])] = r["ns_per_op"]
            if r["role"] == "test":
                strides.add(r["stride"])
    blks = sorted(b for b, cell in by_blk.items() if (REF_STRIDE, "ref") in cell)
    ratios = {
        s: np.array(
            [np.log(by_blk[b][(s, "test")] / by_blk[b][(REF_STRIDE, "ref")]) for b in blks if (s, "test") in by_blk[b]],
            dtype=float,
        )
        for s in sorted(strides)
    }
    sent = np.array(
        [
            np.log(by_blk[b][(REF_STRIDE, "sentinel")] / by_blk[b][(REF_STRIDE, "ref")])
            for b in blks
            if (REF_STRIDE, "sentinel") in by_blk[b]
        ],
        dtype=float,
    )
    return ratios, sent


def paired_t(d: np.ndarray) -> tuple[float, float, float, float]:
    """One-sided upper-tail paired t-test with explicit zero-SD guard."""
    arr = np.asarray(d, dtype=float)
    n = len(arr)
    mean = float(np.mean(arr))
    sd = float(np.std(arr, ddof=1)) if n >= 2 else 0.0
    if sd == 0.0:
        if mean > 0.0:
            return mean, 0.0, float("inf"), 0.0
        if mean < 0.0:
            return mean, 0.0, float("-inf"), 1.0
        return 0.0, 0.0, 0.0, 1.0
    t_stat = mean / (sd / np.sqrt(n))
    p_val = float(student_t.sf(t_stat, df=n - 1))
    return mean, sd, float(t_stat), p_val


def holm(pvals: list[float]) -> list[float]:
    """Holm-Bonferroni step-down adjusted p-values."""
    m = len(pvals)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: pvals[i])
    adj = [1.0] * m
    prev = 0.0
    for rank, idx in enumerate(order):
        val = min(1.0, (m - rank) * pvals[idx])
        prev = max(prev, val)
        adj[idx] = prev
    return adj


def mde90(sd: float, b_blocks: int, m: int = M_PRIMARY, alpha: float = ALPHA_FW) -> float:
    """Empirical 90%-power MDE fraction on paired log-ratio scale."""
    if sd == 0.0 or b_blocks < 2:
        return 0.0
    t_crit = float(student_t.ppf(1.0 - alpha / m, df=b_blocks - 1))
    t_pow = float(student_t.ppf(0.90, df=b_blocks - 1))
    return float(np.exp((t_crit + t_pow) * sd / np.sqrt(b_blocks)) - 1.0)


def ci99_simultaneous(mean: float, sd: float, b_blocks: int, m: int = M_PRIMARY) -> tuple[float, float]:
    """Simultaneous Bonferroni 99% interval in percentage slowdown units."""
    if b_blocks < 2 or sd == 0.0:
        pct = float((np.exp(mean) - 1.0) * 100.0)
        return pct, pct
    q = float(student_t.ppf(1.0 - 0.01 / (2.0 * m), df=b_blocks - 1))
    half = q * sd / np.sqrt(b_blocks)
    return float((np.exp(mean - half) - 1.0) * 100.0), float((np.exp(mean + half) - 1.0) * 100.0)


def sentinel_drift(sent_d: np.ndarray) -> bool:
    """Detect zero-mean shift (two-sided p<=0.01) or lag-1 autocorrelation drift."""
    arr = np.asarray(sent_d, dtype=float)
    b = len(arr)
    if b < 4:
        return False
    mean, sd, _, _ = paired_t(arr)
    p_two = (
        0.0
        if (sd == 0.0 and abs(mean) > 0.0)
        else (1.0 if sd == 0.0 else float(2.0 * student_t.sf(abs(mean) / (sd / np.sqrt(b)), df=b - 1)))
    )
    x, y = arr[:-1], arr[1:]
    r1 = float(np.corrcoef(x, y)[0, 1]) if (np.std(x) > 0.0 and np.std(y) > 0.0) else 0.0
    return bool((p_two <= ALPHA_FW) or (abs(r1) > 2.0 / np.sqrt(b)))
