"""Monte Carlo validator for ST-01, ST-02, and ST-03."""

from __future__ import annotations

import numpy as np

from .classify import classify_config
from .stats import (
    ALPHA_FW,
    EFFECT_FLOOR,
    M_PRIMARY,
    PRIMARY_STRIDES,
    holm,
    mde90,
    paired_t,
)


def simulate_sweep(
    sigma: float,
    rho: float,
    effect: float,
    b_blocks: int = 30,
    seed: int = 0,
    spike_rate: float = 0.0,
) -> dict:
    """Simulate one sweep across 5 primary strides + ref 256 + sentinel 256_B."""
    rng = np.random.default_rng(seed)
    z = rng.normal(0.0, np.sqrt(rho) * sigma, size=(b_blocks, 1)) if rho > 0.0 else np.zeros((b_blocks, 1))
    eps = rng.normal(0.0, np.sqrt(1.0 - rho) * sigma, size=(b_blocks, 7))
    log_y = z + eps
    if spike_rate > 0.0:
        log_y += np.log(1.20) * (rng.random((b_blocks, 7)) < spike_rate)
    if effect != 0.0:
        log_y[:, 3] += np.log(1.0 + effect)  # stride 64 is index 3 in (8,16,32,64,128)

    d_mat = log_y[:, :5] - log_y[:, 5:6]
    sent_d = log_y[:, 6] - log_y[:, 5]
    _, sent_sd, _, _ = paired_t(sent_d)
    sent_mde = mde90(sent_sd, b_blocks, m=M_PRIMARY, alpha=ALPHA_FW)

    means, pvals = [], []
    for idx in range(5):
        mean, _, _, p_raw = paired_t(d_mat[:, idx])
        means.append(mean)
        pvals.append(p_raw)
    padj = holm(pvals)
    contended = {
        s: (padj[i] <= ALPHA_FW and (np.exp(means[i]) - 1.0) > EFFECT_FLOOR) for i, s in enumerate(PRIMARY_STRIDES)
    }
    cls, k_bytes, gate_st, _ = classify_config(
        {"mde90": sent_mde, "contended": contended, "faster_wider": []}, gate=0.10
    )
    return {
        "false_positive": any(contended.values()),
        "detected_64": bool(contended[64]),
        "class": cls,
        "knee_bytes": k_bytes,
        "gate": gate_st,
        "mde90": sent_mde,
    }


def run_st01_st03() -> bool:
    """Execute ST-01 (2,000 sweeps), ST-02 (1,000 sweeps), ST-03 (2,000 sweeps)."""
    grid = [
        (0.01, 0.0),
        (0.01, 0.3),
        (0.02, 0.0),
        (0.02, 0.3),
        (0.03, 0.0),
        (0.03, 0.3),
    ]
    fp_st01 = 0
    for i in range(2000):
        sig, rho = grid[i % len(grid)]
        if simulate_sweep(sig, rho, effect=0.0, seed=10000 + i)["false_positive"]:
            fp_st01 += 1
    fwer_st01 = fp_st01 / 2000.0

    det_st02 = 0
    for i in range(1000):
        rho = 0.0 if i % 2 == 0 else 0.3
        if simulate_sweep(0.03, rho, effect=0.05, seed=20000 + i)["detected_64"]:
            det_st02 += 1
    pwr_st02 = det_st02 / 1000.0

    fp_st03 = 0
    for i in range(2000):
        sig, rho = grid[i % len(grid)]
        if simulate_sweep(sig, rho, effect=0.0, seed=30000 + i, spike_rate=0.08)["false_positive"]:
            fp_st03 += 1
    fwer_st03 = fp_st03 / 2000.0

    p1 = fwer_st01 <= 0.015
    p2 = pwr_st02 >= 0.90
    p3 = fwer_st03 <= 0.015
    print(f"ST-01 FWER={fwer_st01 * 100:.2f}% (limit <= 1.50%): {'PASS' if p1 else 'FAIL'}")
    print(f"ST-02 Power@64={pwr_st02 * 100:.2f}% (limit >= 90.00%): {'PASS' if p2 else 'FAIL'}")
    print(f"ST-03 Spiky FWER={fwer_st03 * 100:.2f}% (limit <= 1.50%): {'PASS' if p3 else 'FAIL'}")
    return p1 and p2 and p3
