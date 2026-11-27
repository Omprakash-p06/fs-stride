"""CLI entrypoint for fs-stride analysis and Monte Carlo validation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

from .classify import classify_config, is_primary_config
from .folklore import compare, load_folklore
from .io import load_meta, load_raw
from .report import make_figures, write_report
from .sim import run_st01_st03
from .stats import (
    ALPHA_FW,
    EFFECT_FLOOR,
    M_PRIMARY,
    PRIMARY_STRIDES,
    REF_STRIDE,
    ci99_simultaneous,
    holm,
    log_ratios,
    mde90,
    paired_t,
    sentinel_drift,
)


def _cell(mode, thr, plc, stride, role, arr, primary=False):
    mean, sd, _, p_raw = paired_t(arr)
    lo, hi = ci99_simultaneous(mean, sd, len(arr), m=M_PRIMARY)
    # fmt: off
    return {"mode": mode, "threads": thr, "placement": plc, "stride": stride, "role": role,
            "n_blocks": len(arr), "mean_log_ratio": mean, "sd": sd,
            "effect_pct": (np.exp(mean) - 1.0) * 100.0,
            "ci99_low_pct": lo, "ci99_high_pct": hi, "p_raw": p_raw, "p_holm": None,
            "primary": primary, "contended": False}
    # fmt: on


def _config(mode, thr, plc, prim, knee_bytes, cls, mde_pct, gate, drift, reason):
    # fmt: off
    return {"mode": mode, "threads": thr, "placement": plc, "primary": prim,
            "knee_bytes": knee_bytes, "class": cls, "mde90_pct": mde_pct,
            "gate": gate, "drift_alert": drift, "reason": reason}
    # fmt: on


def analyze_run(
    run_dir: Path,
    compare_folklore: bool = False,
    strict_h1: bool = False,
    folklore_path: Path | None = None,
) -> int:
    """Run statistical inference and write outputs for a benchmark run directory."""
    raw_path, meta_path = run_dir / "raw.csv", run_dir / "meta.json"
    if not raw_path.is_file() or not meta_path.is_file():
        print("run fs_stride first: missing raw.csv or meta.json", file=sys.stderr)
        return 1
    try:
        rows = load_raw(raw_path)
        meta = load_meta(meta_path)
    except ValueError as exc:
        code = 3 if "empty cpus" in str(exc) else 1
        print(f"error: {exc}", file=sys.stderr)
        return code
    if not rows:
        print("run fs_stride first: no non-warmup rows", file=sys.stderr)
        return 1

    gate = 0.05 if strict_h1 else 0.10
    configs_keys = sorted({(r["mode"], r["threads"], r["placement"]) for r in rows})
    max_t = max(k[1] for k in configs_keys)
    single_thread_only = {k[1] for k in configs_keys} == {1}

    cells_out, configs_out, n_blocks_max = [], [], 2
    for mode, thr, plc in configs_keys:
        ratios, sent_d = log_ratios(rows, (mode, thr, plc))
        if len(sent_d) < 2:
            continue
        b_cnt = len(sent_d)
        n_blocks_max = max(n_blocks_max, b_cnt)
        prim = is_primary_config(mode, thr, max_t, plc)
        _, sent_sd, _, _ = paired_t(sent_d)
        sent_mde = mde90(sent_sd, b_cnt, m=M_PRIMARY, alpha=ALPHA_FW)
        cells_out.append(_cell(mode, thr, plc, REF_STRIDE, "sentinel", sent_d))

        prim_items, faster_wider, test_rows = [], [], []
        for stride, arr in sorted(ratios.items()):
            mean, _, _, _ = paired_t(arr)
            eff_frac = float(np.exp(mean) - 1.0)
            entry = _cell(mode, thr, plc, stride, "test", arr, bool(prim and stride in PRIMARY_STRIDES))
            if stride in PRIMARY_STRIDES:
                prim_items.append(entry)
            if stride >= REF_STRIDE:
                _, _, _, p_left = paired_t(-arr)
                if p_left <= ALPHA_FW and eff_frac < -EFFECT_FLOOR:
                    faster_wider.append({"stride": stride, "effect_pct": eff_frac * 100.0})
            test_rows.append(entry)

        padj = holm([e["p_raw"] for e in prim_items])
        contended_map: dict[int, bool] = {}
        for entry, p_h in zip(prim_items, padj):
            entry["p_holm"] = p_h
            is_c = bool(p_h <= ALPHA_FW and (entry["effect_pct"] / 100.0) > EFFECT_FLOOR)
            entry["contended"] = is_c
            contended_map[entry["stride"]] = is_c
        for entry in test_rows:
            if entry["stride"] not in PRIMARY_STRIDES:
                entry["contended"] = bool(entry["p_raw"] <= ALPHA_FW and (entry["effect_pct"] / 100.0) > EFFECT_FLOOR)
        cells_out.extend(test_rows)

        cls, k_bytes, gate_st, reason = classify_config(
            {
                "mde90": sent_mde,
                "contended": contended_map,
                "faster_wider": faster_wider,
                "single_thread": single_thread_only,
            },
            gate=gate,
        )
        configs_out.append(
            _config(mode, thr, plc, prim, k_bytes, cls, sent_mde * 100.0, gate_st, sentinel_drift(sent_d), reason)
        )

    fpath = folklore_path or (Path(__file__).resolve().parents[2] / "data" / "folklore.toml")
    folklore_rows = (
        compare(configs_out, load_folklore(fpath), meta.get("arch", "x86_64"))
        if (compare_folklore or fpath.is_file())
        else []
    )
    # fmt: off
    summary = {"schema_version": "2.0", "run_id": rows[0]["run_id"], "host": rows[0]["host"],
               "n_blocks": n_blocks_max, "alpha_fw": ALPHA_FW, "m_primary": M_PRIMARY,
               "effect_floor_pct": 1.0, "mde90_gate_pct": 5.0 if strict_h1 else 10.0,
               "strict_h1": strict_h1, "cells": cells_out, "configs": configs_out,
               "folklore": folklore_rows}
    # fmt: on
    env_log = (run_dir / "env.log").read_text(encoding="utf-8") if (run_dir / "env.log").is_file() else ""
    make_figures(summary, run_dir)
    write_report(summary, meta, env_log, run_dir)
    for c in configs_out:
        print(
            f"mode={c['mode']} threads={c['threads']} placement={c['placement']} knee={c['knee_bytes'] or 'n/a'} mde90={c['mde90_pct']:.2f}% class={c['class']}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    """Parse CLI arguments and dispatch analyze or sim."""
    p = argparse.ArgumentParser(prog="fs-stride-analyze")
    sub = p.add_subparsers(dest="cmd", required=True)
    pa = sub.add_parser("analyze")
    pa.add_argument("run_dir", type=Path)
    pa.add_argument("--compare-folklore", action="store_true")
    pa.add_argument("--strict-h1", action="store_true")
    pa.add_argument("--folklore", type=Path, default=None)
    sub.add_parser("sim")
    try:
        args = p.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code != 0 else 0
    if args.cmd == "sim":
        return 0 if run_st01_st03() else 1
    return analyze_run(args.run_dir, args.compare_folklore, args.strict_h1, args.folklore)


if __name__ == "__main__":
    raise SystemExit(main())
