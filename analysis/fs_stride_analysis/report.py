"""Markdown, CSV, JSON, and Matplotlib report generators."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def _pick(cells: list[dict], cfg: dict, role: str) -> list[dict]:
    # fmt: off
    return [c for c in cells if c["mode"] == cfg["mode"] and c["threads"] == cfg["threads"]
            and c["placement"] == cfg["placement"] and c["role"] == role]
    # fmt: on


def make_figures(summary: dict, outdir: Path) -> None:
    """Write per-config effect curves and sentinel distribution histogram."""
    figs = outdir / "figs"
    figs.mkdir(parents=True, exist_ok=True)
    cells = summary["cells"]
    for cfg in summary["configs"]:
        sub = _pick(cells, cfg, "test")
        sent = _pick(cells, cfg, "sentinel")
        if not sub:
            continue
        sub.sort(key=lambda x: x["stride"])
        xs = [c["stride"] for c in sub]
        ys = [c["effect_pct"] for c in sub]
        lo = [c["effect_pct"] - c["ci99_low_pct"] for c in sub]
        hi = [c["ci99_high_pct"] - c["effect_pct"] for c in sub]
        fig, ax = plt.subplots(figsize=(6.5, 4.0))
        ax.errorbar(xs, ys, yerr=[lo, hi], fmt="o-", capsize=4, label="Effect vs 256 B")
        if sent:
            ax.axhspan(
                sent[0]["ci99_low_pct"], sent[0]["ci99_high_pct"], alpha=0.2, color="gray", label="Sentinel 99% band"
            )
        if cfg["knee_bytes"]:
            ax.axvline(cfg["knee_bytes"], color="red", linestyle="--", label=f"Knee={cfg['knee_bytes']} B")
        ax.axhline(0.0, color="black", linewidth=0.8)
        ax.set_xscale("log", base=2)
        ax.set_xticks(xs)
        ax.set_xticklabels([str(x) for x in xs])
        ax.set_xlabel("Stride (bytes)")
        ax.set_ylabel("Slowdown vs 256 B (%)")
        ax.set_title(f"{cfg['mode']} | t={cfg['threads']} | {cfg['placement']} ({cfg['class']})")
        ax.legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(figs / f"curve_{cfg['mode']}_{cfg['threads']}_{cfg['placement']}.png", dpi=150)
        plt.close(fig)

    sent_vals = [c["effect_pct"] for c in cells if c["role"] == "sentinel"]
    fig, ax = plt.subplots(figsize=(5.5, 3.5))
    ax.hist(sent_vals or [0.0], bins=min(15, max(3, len(sent_vals))), edgecolor="black")
    ax.set_xlabel("Sentinel 256_B mean difference (%)")
    ax.set_ylabel("Configurations")
    ax.set_title("Paired A/A Sentinel Distribution")
    fig.tight_layout()
    fig.savefig(figs / "sentinel_hist.png", dpi=150)
    plt.close(fig)


def write_report(summary: dict, meta: dict, env_log: str, outdir: Path) -> None:
    """Write summary.json, summary.csv, and report.md."""
    (outdir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    with (outdir / "summary.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["host", "mode", "threads", "placement", "mde90_pct", "knee_bytes", "class"])
        for c in summary["configs"]:
            kb = "n/a" if c["knee_bytes"] is None else str(c["knee_bytes"])
            w.writerow(
                [summary["host"], c["mode"], c["threads"], c["placement"], f"{c['mde90_pct']:.2f}", kb, c["class"]]
            )

    prim = [c for c in summary["configs"] if c["primary"]]
    expl = [c for c in summary["configs"] if not c["primary"]]
    # fmt: off
    lines = [
        f"# fs-stride Report: `{summary['run_id']}`", "",
        "## Hardware & Environment", "",
        f"- **Host / Arch:** `{summary['host']}` (`{meta.get('arch', 'unknown')}`, `{meta.get('cpu_model', 'unknown')}`)",
        f"- **Blocks (`B`):** {summary['n_blocks']} | **Gate:** MDE90 <= {summary['mde90_gate_pct']:.1f}% | **Shared host:** {meta.get('shared_host', False)}",
        f"- **Compiler / Atomic:** `{meta.get('compiler', 'unknown')}` / `{meta.get('atomic_opcode', 'unknown')}`", "",
        "```text", env_log.strip() or "(no env.log provided)", "```", "",
        "## Noise Gate & Primary Results", "",
        "| Mode | Threads | Placement | MDE90 (%) | Gate | Drift Alert | Knee (B) | Class |",
        "| :--- | :---: | :--- | :---: | :--- | :---: | :---: | :--- |",
    ]
    # fmt: on
    for c in prim:
        lines.append(
            f"| {c['mode']} | {c['threads']} | {c['placement']} | {c['mde90_pct']:.2f} | {c['gate']} | {c['drift_alert']} | {c['knee_bytes'] or 'n/a'} | {c['class']} |"
        )
    # fmt: off
    lines.extend(["", "## Exploratory Results", "",
                  "| Mode | Threads | Placement | MDE90 (%) | Knee (B) | Class | Note |",
                  "| :--- | :---: | :--- | :---: | :---: | :--- | :--- |"])
    # fmt: on
    for c in expl:
        lines.append(
            f"| {c['mode']} | {c['threads']} | {c['placement']} | {c['mde90_pct']:.2f} | {c['knee_bytes'] or 'n/a'} | {c['class']} | {c['reason'] or '-'} |"
        )
    if summary["folklore"]:
        # fmt: off
        lines.extend(["", "## Folklore Comparison", "",
                      "| Ecosystem | Mode | Threads | Placement | Measured (B) | Folklore (B) | Agree |",
                      "| :--- | :--- | :---: | :--- | :---: | :---: | :--- |"])
        # fmt: on
        for f in summary["folklore"]:
            lines.append(
                f"| {f['ecosystem']} | {f['mode']} | {f['threads']} | {f['placement']} | {f['measured_knee_bytes'] or 'n/a'} | {f['folklore_bytes']} | {f['agree']} |"
            )
    # fmt: off
    lines.extend(["", "## Limitations", "",
                  f"- Measured on 1 machine (`{summary['host']}`) across `B = {summary['n_blocks']}` randomized blocks (block 0 discarded as warm-up).",
                  "- No PMU counters or causal MSR prefetcher ablation attached unless run via Phase 2 sidecars."])
    # fmt: on
    (outdir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
