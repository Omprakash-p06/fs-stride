# ADR 0002: 5-File C Architecture, Modes, Placements, `posix_memalign`, and `K=65,536` Loop

- **Status:** Accepted
- **Date:** 2026-11-27
- **Decides:** C module boundaries, kernel modes, CPU placements, memory allocation, chunk timing loop, and 14-column `raw.csv` (`docs/decisions.md` #1–#7).

## Context

`RESEARCH_PLAN.md` uncovered four microarchitectural and runtime defects in Draft 1.0 (store-buffer masking in `volatile` loops, zero ongoing L2 misses in single-counter tight loops, strict C11 `aligned_alloc` violations, and `OMP_PROC_BIND`/`OMP_PLACES` pinning divergence) and a 15-minute NFR-01 wall-clock breach from doubling calibration.

## Options Considered

1. **Monolithic `src/fs_stride.c` with `1,024`-op stop-flag polling and 10-col CSV:** Rejected; prevents isolated `UT-04` disassembly / `UT-02` allocator tests, increases barrier/timer overhead under 22× contention, and omits `run_id`, `role`, `cpus`, and `loadavg1`.
2. **Modular 5-file C layout with `K = 65,536` chunked loop and 14-col CSV:** Chosen.

## Decision

1. **C layout:** 5 files (`src/main.c`, `src/topo.c`, `src/alloc.c`, `src/kernel.c`, `src/fs_stride.h`) using `fs_mode_t` (avoiding POSIX `<sys/types.h>` `mode_t` collision under `-Werror`).
2. **Modes:** `atomic` (Regime A, H2), `coupled-pair` (Regime B, 4 KB ping-pong for H1, even threads `>= 4`), `volatile` (store-buffer control, H4), and `rw-asymmetric` (diagnostic reader/writer).
3. **Placements:** `cores` (1 thread/physical core, intra-socket/LLC first), `smt-sibling` (2 threads/physical core, exploratory-only), and `spread` (cross-socket/package, allowed on `cores`-equivalent primaries). Pinning uses `sched_setaffinity` inside `#pragma omp parallel` from `sysfs` topology (`topo_load` accepts `sysfs_root` for `UT-01`).
4. **Allocator:** `posix_memalign(&ptr, 4096, round_up_4096(raw_size))`, `memset`, `atomic_init`, and `_Static_assert(ATOMIC_LLONG_LOCK_FREE == 2)`. Warn in `meta.json` whenever `threads * stride >= 4096`.
5. **Timing & `raw.csv`:** `K = 65,536` ops per chunk (`barrier -> t_start -> K ops -> barrier -> check elapsed >= target -> repeat`). `UT-14` allows `50–100 ms` on dev machines with `"warning only"` if `(last_chunk_duration / cell_duration) > 0.25`. Emit 14 columns (`run_id,host,mode,stride,threads,placement,block,order,role,total_ops,elapsed_s,ns_per_op,cpus,loadavg1`) with `total_ops` summed across all threads and `ns_per_op = elapsed_s * 1e9 * threads / total_ops`.

## Consequences & Blast Radius

- Directly governs `src/fs_stride.h`, future `src/*.c`, `schemas/raw.schema.json`, `scripts/capture_meta.sh`, and `UT-01`–`UT-06` / `UT-14`.
- AArch64 builds use `-mno-outline-atomics` so `UT-04` observes inline `ldadd`/`ldxr` instructions inside `run_cell`.
