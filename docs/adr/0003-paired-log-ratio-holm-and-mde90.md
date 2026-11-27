# ADR 0003: Paired Log-Ratio Holm (`m=5`), 1% Floor, `MDE90` Gate, and `s >= s*` Knee Rule

- **Status:** Accepted
- **Date:** 2026-11-27
- **Decides:** Inference family, multiplicity control, effect floor, noise gate units, knee predicate, `irregular` handling, and statistical validation (`docs/decisions.md` #8–#12, #14–#15).

## Context

Draft 1.0 suffered from unit confusion (`ln` vs linear ratios), a 20.04× variance-scaling mismatch causing a 2.90% CV cliff, a `CI_upper <= 1 + delta` direction paradox (92.94% FWER), a 31.06% spurious ST-01 failure rate, and BCa median jackknife `NaN` failures.

## Options Considered

1. **Unadjusted 99% CIs, `m=6` including `512`, `2%` floor, and `s > s*` knee rule:** Rejected; `512` is not part of FR-11's primary family, `2%` masks subtle 2–3% H1 effects, and `s > s*` shifts reported knees down by one stride step (`64` instead of `128`).
2. **Within-block paired log-ratio t-test with Holm (`m=5`), 1% floor, `MDE90` gate, and `s >= s*` knee:** Chosen.

## Decision

1. **Primary family (`m = 5`):** Strides `8, 16, 32, 64, 128` vs `256` B reference for `atomic` and `coupled-pair` on `cores`/`spread` at max tested thread count (`alpha_FW = 0.01`, Holm step-down per config). Stride `512`, `volatile`, `rw-asymmetric`, `smt-sibling`, and `t < max` are exploratory (reported with `primary = false` in the exploratory table).
2. **Contention & intervals:** Contended iff `p_holm <= 0.01` and `exp(mean_log_ratio) - 1 > 0.01` (1% floor). Simultaneous 99% CIs use Bonferroni `scipy.stats.t.ppf(1 - 0.01 / (2 * m), B - 1)` converted to `%`.
3. **`MDE90` noise gate:** Computed internally as fraction `exp((t(B-1, 1-alpha/m) + t(B-1, 0.90)) * sd / sqrt(B)) - 1`, gated at `mde90 > 0.10` (`> 0.05` under `--strict-h1`), and serialized as `mde90_pct = 100 * mde90`. Sentinel `256_B` also sets `drift_alert` on two-sided zero-mean `p <= 0.01` or `|r1| > 2 / sqrt(B)`.
4. **Knee & `512 < 256`:** `knee = s*` where `s*` is the smallest stride such that `s*` is uncontended AND every stride `s > s*` is uncontended. A significant `512 < 256` speedup classifies as `irregular`, sets `knee_bytes = null` (`n/a` in CSV), and logs `log.warning("faster-wider detected at stride %d; not a knee", s)`.
5. **Blocks, ST, CLI, & Folklore:** `B = 30` (31 blocks with block 0 warm-up discarded); `ST-01` = 2,000 null sweeps (`FWER <= 1.5%`); `ST-02` = 1,000 sweeps with 5% slowdown at stride 64 only (per-stride Holm power `>= 90%`); `cli.py` exit codes `0..3` only; `data/folklore.toml` covers all 7 ecosystems; `docs/related-work.md` cites both CPython `gh-144438` and `#159860`.

## Consequences & Blast Radius

- Directly governs `analysis/fs_stride_analysis/{io,stats,classify,sim,folklore,report,cli}.py`, `schemas/summary.schema.json`, `data/folklore.toml`, and `UT-07`–`UT-13` / `ST-01`–`ST-03`.
- Frozen invariants in `AGENTS.md` §0.3 (`paired_t`, `holm`, `mde90`, `knee`, `classify_config`, `simulate_sweep`, `load_raw`) lock these exact formulas.
