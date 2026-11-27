#!/usr/bin/env bash
# IT-01: end-to-end smoke pipeline (2 strides, 2 thread counts, 5 blocks).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

TMP="$(mktemp -d "${TMPDIR:-/tmp}/fs_stride_smoke.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

START="$(date +%s)"
if ! ./scripts/run_all.sh --out "$TMP/run" \
    --strides 8,256 --threads 1,2 --blocks 5 --target-ms 10 \
    --modes atomic --placements cores >"$TMP/smoke.log" 2>&1; then
    cat "$TMP/smoke.log" >&2
    echo "IT-01 FAIL: smoke pipeline exited non-zero" >&2
    exit 1
fi
ELAPSED=$(($(date +%s) - START))

if grep -q "Traceback" "$TMP/smoke.log"; then
    cat "$TMP/smoke.log" >&2
    echo "IT-01 FAIL: traceback in pipeline log" >&2
    exit 1
fi

for f in raw.csv meta.json summary.json summary.csv report.md env.log \
    figs/sentinel_hist.png figs/curve_atomic_1_cores.png; do
    if [ ! -e "$TMP/run/$f" ]; then
        echo "IT-01 FAIL: missing $f" >&2
        exit 1
    fi
done

PYTHON="${PYTHON:-}"
if [ -z "$PYTHON" ]; then
    if [ -x "$ROOT/.venv/bin/python3" ]; then PYTHON="$ROOT/.venv/bin/python3"; else PYTHON=python3; fi
fi
PYTHONPATH="$ROOT/analysis" "$PYTHON" - "$TMP/run" "$ROOT/schemas" <<'PY'
import json
import sys
from pathlib import Path

import jsonschema

run, schemas = Path(sys.argv[1]), Path(sys.argv[2])
for schema, payload in (("meta.schema.json", "meta.json"), ("summary.schema.json", "summary.json")):
    jsonschema.validate(
        json.loads((run / payload).read_text()), json.loads((schemas / schema).read_text())
    )
print("IT-01 schemas PASS")
PY

if [ "$ELAPSED" -ge 60 ]; then
    echo "IT-01 FAIL: ${ELAPSED}s exceeds the 60 s budget" >&2
    exit 1
fi

echo "IT-01 PASS (${ELAPSED}s)"
