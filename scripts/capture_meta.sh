#!/usr/bin/env bash
set -euo pipefail

BIN="./fs_stride"
OUT="meta.json"
SEED="42"
COMPILER="${CC:-gcc}"
CFLAGS_VAL="-O2 -fopenmp -std=c11 -Wall -Wextra -Werror -D_GNU_SOURCE"
OMP_THREADS_ARG=""

while [ "$#" -gt 0 ]; do
    case "$1" in
        --bin) BIN="$2"; shift 2 ;;
        --out) OUT="$2"; shift 2 ;;
        --seed) SEED="$2"; shift 2 ;;
        --compiler) COMPILER="$2"; shift 2 ;;
        --cflags) CFLAGS_VAL="$2"; shift 2 ;;
        --threads) OMP_THREADS_ARG="$2"; shift 2 ;;
        *) echo "Unknown arg: $1" >&2; exit 2 ;;
    esac
done

PRINT_META="$("$BIN" --seed "$SEED" --print-meta)"
LSCPU_OUT="$(lscpu 2>/dev/null || echo unknown)"
CPU_MODEL="$(printf '%s\n' "$LSCPU_OUT" | awk -F: '/Model name/ {sub(/^[ \t]+/, "", $2); print $2; exit}')"
[ -n "$CPU_MODEL" ] || CPU_MODEL="unknown"
ARCH="$(uname -m 2>/dev/null || echo unknown)"
MICROARCH="$(printf '%s\n' "$LSCPU_OUT" | awk -F: '/Vendor ID|CPU family|Model:/ {gsub(/^[ \t]+/, "", $2); printf "%s ", $2} END {print ""}')"
MICROARCH="${MICROARCH:-$CPU_MODEL}"
MICROARCH="${MICROARCH% }"
[ -n "$MICROARCH" ] || MICROARCH="unknown"
KERNEL="$(uname -r 2>/dev/null || echo unknown)"
GOVERNOR="$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null || echo unknown)"
SMT_RAW="$(cat /sys/devices/system/cpu/smt/active 2>/dev/null || echo unknown)"
case "$SMT_RAW" in 1) SMT="on" ;; 0) SMT="off" ;; *) SMT="$SMT_RAW" ;; esac

HYPERVISOR="$(systemd-detect-virt 2>/dev/null || true)"
if [ -z "$HYPERVISOR" ]; then
    HYPERVISOR="$(printf '%s\n' "$LSCPU_OUT" | awk -F: '/Hypervisor vendor/ {sub(/^[ \t]+/, "", $2); print $2; exit}')"
fi
[ -n "$HYPERVISOR" ] || HYPERVISOR="none"

LOADAVG="$(awk '{print $1}' /proc/loadavg 2>/dev/null || echo unknown)"
COMP_VER="$("$COMPILER" --version 2>/dev/null | head -n1 || echo "$COMPILER")"
ATOMIC_OP="$(objdump -d "$BIN" 2>/dev/null | awk '/<chunk_atomic>:/,/^$/' | grep -E '\block\b|ldadd|ldxr' | head -n1 | sed 's/^[ \t]*//' || true)"
[ -n "$ATOMIC_OP" ] || ATOMIC_OP="unknown"
OMP_RT="$(ldd "$BIN" 2>/dev/null | awk '/libg?omp/ {print $1; exit}' || true)"
[ -n "$OMP_RT" ] || OMP_RT="unknown"
GIT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
OMP_PB="${OMP_PROC_BIND:-unset}"
OMP_PL="${OMP_PLACES:-unset}"
OMP_NT="${OMP_NUM_THREADS:-${OMP_THREADS_ARG:-auto}}"

export PRINT_META CPU_MODEL MICROARCH ARCH LSCPU_OUT KERNEL GOVERNOR SMT HYPERVISOR LOADAVG
export COMP_VER CFLAGS_VAL ATOMIC_OP OMP_RT OMP_NT OMP_PB OMP_PL GIT_SHA OUT

python3 - <<'PY'
import json, os
pm = json.loads(os.environ["PRINT_META"])
shared = os.environ["HYPERVISOR"].lower() != "none"
warnings = []
if os.environ["OMP_PB"] != "unset" or os.environ["OMP_PL"] != "unset":
    warnings.append("OMP_PROC_BIND/OMP_PLACES ignored; pinning uses sched_setaffinity")
if pm.get("aliasing_warning"):
    warnings.append("threads * stride >= 4096 detected (L1D set aliasing risk)")
if shared:
    warnings.append(f"shared_host=true (hypervisor={os.environ['HYPERVISOR']})")

meta = {
    "schema_version": "2.0",
    "cpu_model": os.environ["CPU_MODEL"],
    "microarch": os.environ["MICROARCH"],
    "arch": os.environ["ARCH"],
    "lscpu": os.environ["LSCPU_OUT"].strip() or "unknown",
    "kernel": os.environ["KERNEL"],
    "governor": os.environ["GOVERNOR"] or "unknown",
    "smt": os.environ["SMT"] or "unknown",
    "p_core_cpus": str(pm.get("p_core_cpus", "unknown")),
    "e_core_cpus": str(pm.get("e_core_cpus", "unknown")),
    "sysfs_coherency_line_size": pm.get("sysfs_coherency_line_size", "unknown"),
    "hypervisor": os.environ["HYPERVISOR"],
    "loadavg_start": os.environ["LOADAVG"] or "unknown",
    "compiler": os.environ["COMP_VER"] or "unknown",
    "cflags": os.environ["CFLAGS_VAL"] or "unknown",
    "atomic_opcode": os.environ["ATOMIC_OP"] or "unknown",
    "omp_runtime": os.environ["OMP_RT"] or "unknown",
    "omp_num_threads": str(os.environ["OMP_NT"] or "auto"),
    "omp_proc_bind": os.environ["OMP_PB"],
    "omp_places": os.environ["OMP_PL"],
    "git_sha": os.environ["GIT_SHA"] or "unknown",
    "seed": int(pm.get("seed", 42)),
    "shared_host": shared,
    "warnings": warnings,
}
with open(os.environ["OUT"], "w", encoding="utf-8") as fh:
    json.dump(meta, fh, indent=2)
    fh.write("\n")
PY
