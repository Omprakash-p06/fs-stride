#!/usr/bin/env bash
set -euo pipefail
BIN="${FS_STRIDE_BIN:-./fs_stride}"

# UT-05: identical seed -> identical order; every block has each cell once + 1 sentinel; block 0 present
OUT1="$("$BIN" --modes atomic --strides 8,64,256 --threads 2 --placements cores --blocks 3 --target-ms 10 --seed 42)"
OUT2="$("$BIN" --modes atomic --strides 8,64,256 --threads 2 --placements cores --blocks 3 --target-ms 10 --seed 42)"
OUT3="$("$BIN" --modes atomic --strides 8,64,256 --threads 2 --placements cores --blocks 3 --target-ms 10 --seed 99)"

ORD1="$(printf '%s\n' "$OUT1" | awk -F, 'NR>1 {print $3,$4,$5,$6,$7,$8,$9}')"
ORD2="$(printf '%s\n' "$OUT2" | awk -F, 'NR>1 {print $3,$4,$5,$6,$7,$8,$9}')"
ORD3="$(printf '%s\n' "$OUT3" | awk -F, 'NR>1 {print $3,$4,$5,$6,$7,$8,$9}')"

[ "$ORD1" = "$ORD2" ] || { echo "UT-05 FAIL: same seed gave different order" >&2; exit 1; }
[ "$ORD1" != "$ORD3" ] || { echo "UT-05 FAIL: different seeds gave identical order" >&2; exit 1; }

printf '%s\n' "$OUT1" | python3 -c '
import csv, sys
rows = list(csv.DictReader(sys.stdin))
assert len(rows) == 16, f"expected 16 rows, got {len(rows)}"
for b in range(4):
    br = [r for r in rows if int(r["block"]) == b]
    assert len(br) == 4
    pairs = sorted((r["stride"], r["role"]) for r in br)
    assert pairs == [("256", "ref"), ("256", "sentinel"), ("64", "test"), ("8", "test")], pairs
'

# NT-04, NT-06, NT-07
for desc_rc_args in \
    "NT-04|2|--modes atomic --strides 8,256 --threads 999 --blocks 2" \
    "NT-06|2|--modes atomic --strides 12,256 --threads 2 --blocks 2" \
    "NT-07a|2|--modes coupled-pair --strides 8,256 --threads 3 --blocks 2" \
    "NT-07b|2|--modes coupled-pair --strides 8,256 --threads 2 --blocks 2"; do
    IFS='|' read -r tag exp args <<<"$desc_rc_args"
    set +e
    # shellcheck disable=SC2086
    "$BIN" $args >/dev/null 2>&1
    rc=$?
    set -e
    [ "$rc" -eq "$exp" ] || { echo "$tag FAIL: expected exit $exp, got $rc" >&2; exit 1; }
done
echo "UT-05 NT-04 NT-06 NT-07 PASS"
