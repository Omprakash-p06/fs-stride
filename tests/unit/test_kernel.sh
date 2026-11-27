#!/usr/bin/env bash
set -euo pipefail
BIN="${FS_STRIDE_BIN:-./fs_stride}"

OUT="$("$BIN" --modes atomic --strides 256 --threads 1 --placements cores --blocks 3 --target-ms 50)"
printf '%s\n' "$OUT" | python3 -c '
import csv, sys
rows = [r for r in csv.DictReader(sys.stdin) if int(r["block"]) >= 1]
assert len(rows) == 6
for r in rows:
    el = float(r["elapsed_s"])
    assert 0.050 <= el <= 0.100, f"UT-14 cell duration out of [0.050, 0.100]: {el}"
    ns = float(r["ns_per_op"])
    calc = el * 1e9 * int(r["threads"]) / int(r["total_ops"])
    assert abs(ns - calc) <= 1e-3, f"ns_per_op mismatch {ns} vs {calc}"
'

# Verify last_chunk/cell > 0.25 emits warning on tiny target-ms (0.1 ms forces 1 chunk => ratio=1.0)
WARN_OUT="$("$BIN" --modes atomic --strides 8,256 --threads 2 --placements cores --blocks 2 --target-ms 0.1 2>&1 >/dev/null || true)"
printf '%s\n' "$WARN_OUT" | grep -q 'warning: last_chunk/cell=' || {
    echo "UT-14 warning FAIL: expected last_chunk/cell warning, got: $WARN_OUT" >&2
    exit 1
}
echo "UT-14 PASS"
