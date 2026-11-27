#!/usr/bin/env bash
# IT-02..IT-05: repeatability, schema, and cross-compiler reproduction checks.
#
# Full sweeps are expensive. Set REPRO_QUICK=1 for a short local pass
# (fewer blocks, shorter cells) that exercises the same code paths.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

if [ "${REPRO_QUICK:-0}" = "1" ]; then
    BLOCKS="${REPRO_BLOCKS:-5}"
    TARGET_MS="${REPRO_TARGET_MS:-10}"
else
    BLOCKS="${REPRO_BLOCKS:-30}"
    TARGET_MS="${REPRO_TARGET_MS:-50}"
fi
STRIDES="${REPRO_STRIDES:-8,16,32,64,128,256,512}"
THREADS="${REPRO_THREADS:-}"

TMP="$(mktemp -d "${TMPDIR:-/tmp}/fs_stride_repro.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

PYTHON="${PYTHON:-}"
if [ -z "$PYTHON" ]; then
    if [ -x "$ROOT/.venv/bin/python3" ]; then PYTHON="$ROOT/.venv/bin/python3"; else PYTHON=python3; fi
fi

sweep() {
    local out="$1"
    local args=(--out "$out" --strides "$STRIDES" --blocks "$BLOCKS" --target-ms "$TARGET_MS")
    if [ -n "$THREADS" ]; then args+=(--threads "$THREADS"); fi
    ./scripts/run_all.sh "${args[@]}"
}

validate_schemas() {
    PYTHONPATH="$ROOT/analysis" "$PYTHON" - "$1" "$ROOT/schemas" <<'PY'
import json, sys
from pathlib import Path
import jsonschema

run, schemas = Path(sys.argv[1]), Path(sys.argv[2])
for name, payload in (("meta.schema.json", "meta.json"), ("summary.schema.json", "summary.json")):
    jsonschema.validate(json.loads((run / payload).read_text()), json.loads((schemas / name).read_text()))
print(f"schemas PASS: {run.name}")
PY
}

# IT-02: one sweep yields a labeled class (or an inconclusive reason) for every configuration.
sweep "$TMP/run1"
PYTHONPATH="$ROOT/analysis" "$PYTHON" - "$TMP/run1/summary.json" <<'PY'
import json, sys
from pathlib import Path

summary = json.loads(Path(sys.argv[1]).read_text())
allowed = {"flat", "line64", "pair128", "wider", "irregular", "inconclusive"}
assert summary["configs"], "no configurations analyzed"
for cfg in summary["configs"]:
    assert isinstance(cfg.get("primary"), bool), cfg
    assert cfg.get("class") in allowed, cfg
    if cfg["class"] == "inconclusive":
        assert cfg.get("reason"), f"inconclusive without reason: {cfg}"
print(f"IT-02 PASS ({len(summary['configs'])} configurations)")
PY

# IT-03: three sweeps on one machine agree on class and stay within one stride step.
sweep "$TMP/run2"
sweep "$TMP/run3"
if [ "${REPRO_QUICK:-0}" = "1" ]; then
    echo "IT-03 SKIP: REPRO_QUICK=1 cannot reach the noise gate; run without it for the real check"
else
PYTHONPATH="$ROOT/analysis" "$PYTHON" - "$TMP/run1/summary.json" "$TMP/run2/summary.json" "$TMP/run3/summary.json" <<'PY'
import json, sys
from pathlib import Path

def key(c):
    return (c["mode"], c["threads"], c["placement"])

runs = [{key(c): c for c in json.loads(Path(p).read_text())["configs"]} for p in sys.argv[1:]]
steps = [8, 16, 32, 64, 128, 256, 512]

for k, cfg in runs[0].items():
    classes = {r[k]["class"] for r in runs}
    detail = [
        f"{r[k]['class']}(mde90={r[k]['mde90_pct']:.2f}%,knee={r[k]['knee_bytes']})" for r in runs
    ]
    assert len(classes) == 1, f"{k}: classes disagree across runs: {detail}"
    knees = [r[k]["knee_bytes"] for r in runs]
    if any(kn is None for kn in knees):
        assert all(kn is None for kn in knees), f"{k}: knee present in some runs only: {detail}"
        continue
    idx = [steps.index(kn) for kn in knees]
    assert max(idx) - min(idx) <= 1, f"{k}: knees differ by more than one stride step: {detail}"
print(f"IT-03 PASS ({len(runs[0])} configurations, 3 runs)")
PY
fi

# IT-04: a Clang build produces the same schemas and a report.
if command -v clang >/dev/null 2>&1; then
    make BIN="$TMP/fs_stride_clang" CC=clang build >/dev/null
    FS_STRIDE_BIN="$TMP/fs_stride_clang" ./scripts/run_all.sh --out "$TMP/clang" \
        --strides 8,256 --threads 1,2 --blocks 5 --target-ms 10 --modes atomic >/dev/null
    validate_schemas "$TMP/clang"
    [ -f "$TMP/clang/report.md" ] || { echo "IT-04 FAIL: clang run produced no report.md" >&2; exit 1; }
    echo "IT-04 PASS (clang)"
else
    echo "IT-04 SKIP: clang not installed on this host"
fi

# IT-05: AArch64 executes the smoke/repro path and never passes on an affinity failure.
if [ "$(uname -m)" = "aarch64" ]; then
    bash tests/integration/smoke.sh
    validate_schemas "$TMP/run1"
    echo "IT-05 PASS (aarch64)"
else
    echo "IT-05 SKIP: requires an aarch64 host (CI: ubuntu-24.04-arm)"
fi

echo "repro PASS"
