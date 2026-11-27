#!/usr/bin/env bash
set -euo pipefail
BIN="${1:-./fs_stride}"
ARCH="$(uname -m)"
DISASM="$(objdump -d "$BIN")"

ATOMIC_BLK="$(printf '%s\n' "$DISASM" | awk '/<chunk_atomic>:/,/^$/')"
VOL_W_BLK="$(printf '%s\n' "$DISASM" | awk '/<chunk_volatile_write>:/,/^$/')"
VOL_R_BLK="$(printf '%s\n' "$DISASM" | awk '/<chunk_volatile_read>:/,/^$/')"

if [ -z "$ATOMIC_BLK" ] || [ -z "$VOL_W_BLK" ] || [ -z "$VOL_R_BLK" ]; then
    echo "UT-04 FAIL: missing kernel symbol in objdump" >&2
    exit 1
fi

if [ "$ARCH" = "x86_64" ]; then
    printf '%s\n' "$ATOMIC_BLK" | grep -qE '\block\b' || { echo "UT-04 FAIL: no lock prefix in chunk_atomic" >&2; exit 1; }
    ! printf '%s\n' "$VOL_W_BLK" | grep -qE '\block\b' || { echo "UT-04 FAIL: lock found in chunk_volatile_write" >&2; exit 1; }
    ! printf '%s\n' "$VOL_R_BLK" | grep -qE '\block\b' || { echo "UT-04 FAIL: lock found in chunk_volatile_read" >&2; exit 1; }
elif [ "$ARCH" = "aarch64" ]; then
    printf '%s\n' "$ATOMIC_BLK" | grep -qE 'ldadd|ldxr' || { echo "UT-04 FAIL: no ldadd/ldxr in chunk_atomic" >&2; exit 1; }
    ! printf '%s\n' "$VOL_W_BLK" | grep -qE 'ldadd|ldxr' || { echo "UT-04 FAIL: atomic insn in chunk_volatile_write" >&2; exit 1; }
fi
echo "UT-04 PASS ($ARCH)"
