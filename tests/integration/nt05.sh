#!/usr/bin/env bash
# NT-05: run_all.sh refuses to overwrite an existing results directory.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

TMP="$(mktemp -d "${TMPDIR:-/tmp}/fs_stride_nt05.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/run"

set +e
./scripts/run_all.sh --out "$TMP/run" --strides 8,256 --threads 1 --blocks 2 >/dev/null 2>&1
rc=$?
set -e

if [ "$rc" -ne 2 ]; then
    echo "NT-05 FAIL: expected exit 2 for an existing directory, got $rc" >&2
    exit 1
fi

echo "NT-05 PASS"
