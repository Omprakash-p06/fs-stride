#!/usr/bin/env bash
# Full sweep orchestration: benchmark -> metadata -> statistical analysis.
#
# Defaults follow Spec v2.0 NFR-01: B = 30, 52 ms cells, strides 8..512 on
# `cores`, with atomic/volatile at every default thread count and coupled-pair
# at the even counts >= 4 (the kernel rejects other coupled-pair shapes).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN="${FS_STRIDE_BIN:-$ROOT/fs_stride}"
OUT=""
FORCE=0
ANALYZE=1
STRIDES="8,16,32,64,128,256,512"
THREADS_LIST="${THREADS_LIST:-}"
MODES="${MODES:-atomic,volatile,coupled-pair}"
PLACEMENTS="cores"
TARGET_MS=50
BLOCKS=30
SEED=42
SEQUENTIAL=0

usage() {
    cat <<'EOF'
Usage: scripts/run_all.sh [options]

  --out DIR         Output directory (default: results/HOST-UTC)
  --force           Overwrite an existing output directory
  --no-analyze      Collect raw.csv + meta.json only
  --strides LIST    Comma-separated strides (default 8,16,32,64,128,256,512)
  --threads LIST    Comma-separated thread counts (default powers of 2 up to P)
  --modes LIST      Comma-separated modes (default atomic,volatile,coupled-pair)
  --placements LIST Comma-separated placements (default cores)
  --target-ms MS    Cell duration in milliseconds (default 50)
  --blocks N        Measured blocks, block 0 is warm-up (default 30)
  --seed N          Fisher-Yates seed (default 42)
  --sequential      Disable the randomized block order (ST-04)
  -h, --help        Show this help
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --out) OUT="$2"; shift 2 ;;
        --force) FORCE=1; shift ;;
        --no-analyze) ANALYZE=0; shift ;;
        --strides) STRIDES="$2"; shift 2 ;;
        --threads) THREADS_LIST="$2"; shift 2 ;;
        --modes) MODES="$2"; shift 2 ;;
        --placements) PLACEMENTS="$2"; shift 2 ;;
        --target-ms) TARGET_MS="$2"; shift 2 ;;
        --blocks) BLOCKS="$2"; shift 2 ;;
        --seed) SEED="$2"; shift 2 ;;
        --sequential) SEQUENTIAL=1; shift ;;
        -h | --help) usage; exit 0 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

[ -x "$BIN" ] || { echo "missing $BIN; run make build first" >&2; exit 1; }

HOST="$(hostname -s 2>/dev/null || hostname 2>/dev/null || echo host)"
HOST="${HOST//[^A-Za-z0-9._-]/-}"
HOST="${HOST:-host}"
RUN_ID="$HOST-$(date -u +%Y%m%dT%H%M%SZ)"
OUTDIR="${OUT:-$ROOT/results/$RUN_ID}"

case "$OUTDIR" in
    "" | "/" | "." | "..") echo "refusing unsafe output path: '$OUTDIR'" >&2; exit 2 ;;
esac

if [ -e "$OUTDIR" ]; then
    if [ "$FORCE" -ne 1 ]; then
        echo "refusing to overwrite existing $OUTDIR (pass --force)" >&2
        exit 2
    fi
    rm -rf "$OUTDIR"
fi
mkdir -p "$OUTDIR"

if [ -z "$THREADS_LIST" ]; then
    PHYS="$("$BIN" --print-meta | sed -n 's/.*"physical_cores":\([0-9][0-9]*\).*/\1/p')"
    [ -n "$PHYS" ] || { echo "could not detect physical core count" >&2; exit 3; }
    t=1
    while [ "$t" -le "$PHYS" ]; do
        THREADS_LIST="${THREADS_LIST:+$THREADS_LIST,}$t"
        t=$((t * 2))
    done
    if [ "$PHYS" -ge 2 ] && [ $((PHYS & (PHYS - 1))) -ne 0 ]; then
        THREADS_LIST="$THREADS_LIST,$PHYS"
    fi
fi

IFS=',' read -r -a _threads <<<"$THREADS_LIST"
MAX_T=1
for t in "${_threads[@]}"; do
    if [ "$t" -gt "$MAX_T" ]; then MAX_T="$t"; fi
done

CP_THREADS=""
MAIN_MODES=""
HAS_CP=0
IFS=',' read -r -a _modes <<<"$MODES"
for m in "${_modes[@]}"; do
    if [ "$m" = "coupled-pair" ]; then
        HAS_CP=1
    else
        MAIN_MODES="${MAIN_MODES:+$MAIN_MODES,}$m"
    fi
done
for t in "${_threads[@]}"; do
    if [ $((t % 2)) -eq 0 ] && [ "$t" -ge 4 ]; then
        CP_THREADS="${CP_THREADS:+$CP_THREADS,}$t"
    fi
done

PYTHON="${PYTHON:-}"
if [ -z "$PYTHON" ]; then
    if [ -x "$ROOT/.venv/bin/python3" ]; then PYTHON="$ROOT/.venv/bin/python3"; else PYTHON=python3; fi
fi

{
    echo "# fs-stride environment log (AGENTS.md 4.7)"
    echo "run_id=$RUN_ID"
    echo "host=$HOST"
    echo "arch=$(uname -m 2>/dev/null || echo unknown)"
    echo "nproc=$(nproc 2>/dev/null || echo unknown)"
    echo "LEVEL1_DCACHE_LINESIZE=$(getconf LEVEL1_DCACHE_LINESIZE 2>/dev/null || echo unknown)"
    echo "kernel=$(uname -r 2>/dev/null || echo unknown)"
    echo "target_ms=$TARGET_MS"
    echo "blocks=$BLOCKS"
    echo "strides=$STRIDES"
    echo "threads=$THREADS_LIST"
    echo "modes=$MODES"
    echo "placements=$PLACEMENTS"
    echo "seed=$SEED"
    echo "sequential=$SEQUENTIAL"
    echo "OMP_NUM_THREADS=${OMP_NUM_THREADS:-unset}"
    echo "OMP_PROC_BIND=${OMP_PROC_BIND:-unset}"
    echo "OMP_PLACES=${OMP_PLACES:-unset}"
    echo "CC=${CC:-gcc}"
    echo "cc_version=$("${CC:-gcc}" --version 2>/dev/null | head -n1 || echo unknown)"
    if command -v clang >/dev/null 2>&1; then
        echo "clang_version=$(clang --version 2>/dev/null | head -n1)"
    else
        echo "clang_version=unavailable"
    fi
    echo "git_head=$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || echo unknown)"
    echo "loadavg_start=$(awk '{print $1}' /proc/loadavg 2>/dev/null || echo unknown)"
} >"$OUTDIR/env.log"

META_ARGS=(--bin "$BIN" --out "$OUTDIR/meta.json" --seed "$SEED" --threads "$MAX_T")
if [ -n "${CC:-}" ]; then META_ARGS+=(--compiler "$CC"); fi
bash "$ROOT/scripts/capture_meta.sh" "${META_ARGS[@]}"

: >"$OUTDIR/raw.csv"
COMMON=(--strides "$STRIDES" --placements "$PLACEMENTS" --target-ms "$TARGET_MS"
    --blocks "$BLOCKS" --seed "$SEED" --run-id "$RUN_ID" --host "$HOST")
if [ "$SEQUENTIAL" -eq 1 ]; then COMMON+=(--sequential); fi

append_run() {
    local tag="$1"
    shift
    local tmp="$OUTDIR/.cells.$tag"
    local rc=0
    set +e
    "$BIN" "$@" >"$tmp"
    rc=$?
    set -e
    if [ "$rc" -ne 0 ]; then
        rm -f "$tmp"
        echo "fs_stride ($tag) exited $rc" >&2
        exit "$rc"
    fi
    if [ -s "$OUTDIR/raw.csv" ]; then
        tail -n +2 "$tmp" >>"$OUTDIR/raw.csv"
    else
        cat "$tmp" >>"$OUTDIR/raw.csv"
    fi
    rm -f "$tmp"
}

if [ -n "$MAIN_MODES" ]; then
    append_run main --modes "$MAIN_MODES" --threads "$THREADS_LIST" "${COMMON[@]}"
fi
if [ "$HAS_CP" -eq 1 ]; then
    if [ -n "$CP_THREADS" ]; then
        append_run coupled-pair --modes coupled-pair --threads "$CP_THREADS" "${COMMON[@]}"
    else
        echo "warning: coupled-pair needs even thread counts >= 4; skipping" >&2
    fi
fi

if [ ! -s "$OUTDIR/raw.csv" ]; then
    echo "no cells were scheduled; check --modes/--threads/--strides" >&2
    exit 2
fi

if [ "$ANALYZE" -eq 1 ]; then
    PYTHONPATH="$ROOT/analysis" "$PYTHON" -m fs_stride_analysis.cli analyze "$OUTDIR" --compare-folklore
fi

echo "results: $OUTDIR"
