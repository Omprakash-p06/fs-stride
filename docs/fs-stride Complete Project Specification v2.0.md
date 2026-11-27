> **Canonical hierarchy:** `AGENTS.md` > `RESEARCH_PLAN.md` > `Spec v2.0.md` > `README.md` for design decisions; `Spec v2.0.md` > `RESEARCH_PLAN.md` > `AGENTS.md` > `README.md` for interface contracts (FRs, NFRs, test IDs, schemas, CLI flags). Conflicts are resolved in [decisions.md](decisions.md).

# fs-stride: Complete Project Specification v2.0

Measuring the effective false-sharing distance of CPUs. 27 November 2026. This specification consolidates Draft 1.0, the `RESEARCH_PLAN.md` audit, and the post-review canonical decisions in [decisions.md](decisions.md).

Tags: **\[V\]** verified against a primary source; **\[K\]** established domain knowledge, verify before final paper citation; **\[U\]** sourced from internal audit or single third-party note; **\[R\]** author arithmetic or reasoning, not yet executed. Numbers in brackets like `[3]` point to Section 19. Sample values in Section 8 are mock-ups, not measurements.

---

## Part A: Feature & Measurement Specification

### 1. Project Name

- **Name:** `fs-stride`
- **Subtitle:** A reproducible stride-sweep benchmark and paired-statistics analysis for the effective false-sharing distance of CPUs.
- **Slugs:** repo `fs-stride`; C binary `fs_stride`; Python package `fs_stride_analysis`.
- **License:** MIT for original code. No code is copied from external repositories (see Section 15); any third-party attribution is listed in `NOTICE` with its upstream license.

### 2. Project Purpose

#### Problem
Programmers pad per-thread data to avoid false sharing, but padding distances rely on folklore that differs by 2× to 4× across ecosystems: `crossbeam-utils` pads 128 B on x86-64, AArch64, and powerpc64, 256 B on s390x, 32 B on arm/mips/riscv32, and 64 B elsewhere `[2]`; `Facebook Folly` uses `(kIsArchArm || kIsArchS390X) ? 64 : 128`; HotSpot JVM `@Contended` defaults to 128 B `[5]`; Go `CacheLinePadSize` uses 64 B on x86-64, 128 B on arm64, and 256 B on s390x; Linux `L1_CACHE_BYTES` uses 64 B on x86-64, 64–256 B on arm64, and 256 B on s390x; C++17 `std::hardware_destructive_interference_size` uses 64 B on x86-64 and 64–256 B on AArch64 `[6]`; and CPython 3.15 fixed two distinct QSBR false-sharing regressions (`gh-144438` at 64 B `[9]` and Issue `#159860` moving from 64 B to 128 B on Apple M4 Pro). Counter-based tools (`SC'13` `[1]`, `perf c2c` `[3][4]`, Sheriff `[10]`, Predator `[11]`, Cheetah `[12]`, Huron `[13]`) identify *where* false sharing occurs rather than *how far apart* data must be padded.

#### Benchmark Instrument
`fs-stride` is a C11/OpenMP microbenchmark and Python statistical pipeline for Linux x86-64 and AArch64 hosts with sysfs CPU topology (`NFR-03`). It sweeps byte strides between per-thread counters, measures noise inside every randomized block via a paired `256_B` sentinel, and reports the *knee* (smallest uncontended stride beyond which no larger stride is contended) with simultaneous 99% confidence intervals and an explicit `inconclusive` verdict when trial noise exceeds the `MDE90` gate. The default path requires no hardware PMU counters and no root privileges.

#### Hypotheses (Falsifiable)
- **H1:** On Intel x86-64 physical-core placement (`cores`, `threads >= 4` even) with the L2 adjacent-line prefetcher active, `coupled-pair` mode exhibits a statistically significant slowdown at 64 B spacing relative to 128 B spacing (`pair128` knee).
- **H2:** Under `atomic` mode (`cores` placement), the empirical knee matches hardware coherency granularity (64 B on typical x86-64, 128 B on parts with 128 B L2/SLC granularity such as Apple silicon) even when OS-reported L1D line size (`CTR_EL0` / `getconf`) reports 64 B.
- **H3:** On shared cloud VMs, the `MDE90` noise gate classifies a higher fraction of configurations as `inconclusive` than on unloaded bare-metal hosts under identical sweep parameters.
- **H4:** Under `volatile` mode on modern Intel hardware, plain load-add-store false sharing is masked relative to `atomic` mode due to intra-core store-buffer forwarding (evaluated via reported confidence intervals and descriptive `atomic`-vs-`volatile` effect comparison; originally reported in one `[U]` blog post and tested empirically here).

#### Contributions & Non-Goals
- **Contributions:** (a) A paired-block stride-sweep benchmark and noise-gated decision procedure; (b) a reproducible table of measured knees across at least 3 machines compared against 7-ecosystem padding constants `[2][5][6]`; (c) raw datasets and single-command reproduction.
- **Non-Goals:** Not a program profiler or detector for arbitrary applications (use `[3][10][11][12]`); not a claim that padded-vs-unpadded benchmarking is novel `[29]`; `atomic` mode isolates coherency granularity and is not claimed to represent typical non-atomic application code.

### 3. Alternatives Considered

All major design alternatives were evaluated in [RESEARCH_PLAN.md](RESEARCH_PLAN.md) and resolved in [decisions.md](decisions.md):

- **`posix_memalign` vs. `aligned_alloc`:** `aligned_alloc(4096, raw_size)` violates strict ISO C11 when `raw_size` is not a multiple of 4096 (91.4–100% of default cells) and aborts under LLVM Scudo; `posix_memalign(&ptr, 4096, round_up_4096(raw_size))` + `memset` avoids this cleanly (`Defect 3`).
- **`coupled-pair` (4 KB page) vs. L2-eviction streaming ring buffers:** Evicting 0.5–12 MB L2 caches across threads at 2,048 B slot pitch requires 32–1,536 MB buffers that spill out of L3 into DRAM (~80–100 ns latency), swamping L2 spatial prefetcher signals (`Calculation 1`). A 4 KB `coupled-pair` kernel forces continuous L2 RFO misses with zero L2-capacity tuning (`Defect 2`).
- **`sched_setaffinity` (sysfs) vs. `OMP_PROC_BIND` / `OMP_PLACES`:** OpenMP affinity parses environment variables statically at startup and behaves inconsistently across `libgomp`/`libomp` on kernels that enumerate physical cores before SMT siblings (`Defect 4`). Explicit per-thread `sched_setaffinity` inside `#pragma omp parallel` works identically on both runtimes.
- **`K = 65,536` ops per chunk vs. `1,024` ops or doubling calibration:** Doubling calibration overshoots by up to 2× (mean 144.3 ms) and stretches contended cells past 15–60 minutes (`Calculation 3`). `1,024`-op chunks incur heavy barrier/timer overhead under 22× contention; `K = 65,536` with 50 ms time capping executes >330,000 contended ops per cell in ~50–75 ms.
- **Paired log-ratio t-intervals + Holm-Bonferroni vs. BCa median bootstrap & split-half A/A quantile:** BCa on sample medians suffers leave-one-out jackknife degeneracy (`NaN` CIs on flat/quantized data, `Calculation 4`), single-pair A/A calibration suffers a 20.04× variance-scaling mismatch and a 2.90% CV cliff (`Calculation 5`), and split-half 99th-percentile ST-01 fails 31.06% of runs on pure i.i.d. noise (`Calculation 6`).
- **Stdlib `csv` + NumPy vs. `pandas` (`D8`):** Dropping `pandas` removes ~150 MB of CI wheel overhead, eliminates pandas 3.0 Copy-on-Write regressions, and keeps Python analysis under 600 LOC (`RESEARCH_PLAN.md` §"Lean Python Stack").

### 4. Design Decisions Summary

The full 15-row canonical resolution table is maintained in [decisions.md](decisions.md):

1. **C layout:** 5 files (`src/main.c`, `src/topo.c`, `src/alloc.c`, `src/kernel.c`, `src/fs_stride.h`).
2. **Modes:** `atomic`, `coupled-pair`, `volatile`, `rw-asymmetric`.
3. **Placements:** `cores`, `smt-sibling` (exploratory-only), `spread` (allowed on `cores`-equivalent primaries).
4. **Allocator:** `posix_memalign(4096, round_up_4096(size))` + `memset` (+ `atomic_init`).
5. **Chunking:** `K = 65,536`, `barrier -> t_start -> K ops -> barrier -> check`, `UT-14` `50–100 ms` (`warning only` if `last_chunk_duration / cell_duration > 0.25`).
6. **`raw.csv`:** 14 columns (`run_id,host,mode,stride,threads,placement,block,order,role,total_ops,elapsed_s,ns_per_op,cpus,loadavg1`).
7. **`ns_per_op`:** `elapsed_s * 1e9 * threads / total_ops` (`total_ops` = sum across all threads).
8. **Primary family:** `m = 5` (`8, 16, 32, 64, 128` vs `256`; `512` exploratory), `atomic` and `coupled-pair`, `cores`/`spread`, max tested thread count.
9. **Effect floor & `MDE90`:** 1% practical floor; `mde90` fraction internally (`> 0.10`, or `> 0.05` with `--strict-h1`), serialized as `mde90_pct = 100 * mde90`.
10. **Simultaneous CIs:** `scipy.stats.t.ppf(1 - 0.01 / (2 * m), B - 1)` (`m = 5`).
11. **Knee & `512 < 256`:** `knee = s*` (smallest uncontended stride with all `s > s*` uncontended); `512 < 256` -> `irregular`, `knee_bytes = null`, `log.warning("faster-wider detected at stride %d; not a knee", s)`.
12. **Blocks & ST:** `B = 30` (31 blocks with block 0 discarded); `ST-01` = 2,000 sweeps; `ST-02` = 1,000 sweeps (5% slowdown at stride 64 only, per-stride detection power `>= 90%`).
13. **Phasing:** Phase 1 MVP (`T00–T13` + `ci.yml` + weekly `measure.yml` + local pilot); Phase 2 (`T14–T20` after Gate G1).
14. **CI `cloc` & CLI exit codes:** `cloc` (`<= 400` C / `<= 600` Python) hard fail in `ci.yml`; `cli.py` exit codes `0, 1, 2, 3` only (no exit `4`).
15. **MSR ablation & CPython citations:** `msr_ablate.sh` supports `--intel` (`0x1A4` bit 1) and `--amd` (`0xC0000108`, Zen 4/5 only; exit `0` + message otherwise); cite both `gh-144438` and `#159860` in [related-work.md](related-work.md).

### 5. Functional Requirements

| ID | Requirement | Machine-checkable acceptance |
| :--- | :--- | :--- |
| FR-01 | Modes: `atomic` (`atomic_fetch_add_explicit(..., memory_order_relaxed)` on per-thread counter at `i * stride`), `coupled-pair` (threads `2k` and `2k+1` share one atomic counter at slot `k * stride` on distinct physical cores), `volatile` (plain `volatile uint64_t` load-add-store control), `rw-asymmetric` (Thread 0 executes `volatile` writes at offset `0`; Threads `1..T-1` execute `volatile` reads at `i * stride`). | UT-03, UT-04 pass. |
| FR-02 | Strides default to `8,16,32,64,128,256,512` B; stride `256` is the reference; custom list via `--strides` (must include `256` and be multiples of 8, else exit 2). Emit a `meta.json` L1D set-aliasing warning whenever `threads * stride >= 4096`. | NT-06 passes. |
| FR-03 | Counter buffer allocated via `posix_memalign(&ptr, 4096, round_up_4096(raw_size))`, zeroed with `memset` before each cell `[40]`, initialized with `atomic_init`, and verified lock-free via `_Static_assert(ATOMIC_LLONG_LOCK_FREE == 2)`. | UT-02 passes. |
| FR-04 | Thread counts default to powers of 2 up to `P` (`1,2,4,...,2^floor(log2(P))`, plus `P` if non-power-of-two `P >= 2` and `P` is not already included); counts `> P` rejected with exit 2 unless `--oversubscribe`; `coupled-pair` only allows even counts `>= 4` (`3` or `2` rejected with exit 2). | NT-04, NT-07 pass. |
| FR-05 | Each thread pins itself inside `#pragma omp parallel` via `sched_setaffinity` using CPUs from sysfs topology (`topo_load` accepts `sysfs_root` and intersects with initial `sched_getaffinity` mask); placements `cores` (1 thread/physical core, intra-socket/LLC first), `smt-sibling` (2 threads/physical core), `spread` (spread across sockets/packages); `sched_getcpu()` recorded per thread into `raw.csv` `cpus`; exit code 3 on affinity failure `[41]`. | UT-01, NT-08 pass. |
| FR-06 | Hybrid CPUs: default to P-cores only; log `/sys/devices/cpu_core/cpus` and `/sys/devices/cpu_atom/cpus` in `meta.json`. | UT-01 hybrid fixture passes. |
| FR-07 | Each cell runs `--target-ms` (default 50 ms) via chunked execution: `barrier -> record t_start -> execute K = 65,536 ops -> barrier -> check elapsed >= target -> repeat`; `total_ops` is summed across all `threads` threads after exit; `ns_per_op = elapsed_s * 1e9 * threads / total_ops`. | UT-06, UT-14 pass. |
| FR-08 | Blocks consist of one seeded Fisher-Yates permutation (`splitmix64` PRNG, bypassable with `--sequential` for `ST-04`) of all cells plus one `256_B` sentinel (`role=sentinel`) per `(mode, threads, placement)` configuration per block; block 0 is discarded as warm-up; default `B = 30` (31 blocks total, `B >= 2` required). | UT-05 passes. |
| FR-09 | `meta.json` keys (defined in `schemas/meta.schema.json`): `schema_version, cpu_model, microarch, arch, lscpu, kernel, governor, smt, p_core_cpus, e_core_cpus, sysfs_coherency_line_size, hypervisor, loadavg_start, compiler, cflags, atomic_opcode, omp_runtime, omp_num_threads, omp_proc_bind, omp_places, git_sha, seed, shared_host, warnings`. Missing string values become `"unknown"`; `shared_host` is `true` iff `hypervisor != "none"`. | UT-12 passes. |
| FR-10 | Analysis (`python3 -m fs_stride_analysis.cli analyze`) computes within-block paired log ratios `ln(y(s,b)/y(256,b))` (filtering `block == 0`), one-sided paired t-statistics (with explicit `sd == 0` guard), Holm adjustment, `effect_pct = (exp(mean) - 1) * 100`, and Bonferroni simultaneous 99% intervals via `scipy.stats.t.ppf(1 - 0.01 / (2 * m), B - 1)` (`m = 5`). | UT-07 to UT-09 pass. |
| FR-11 | Primary family fixed in advance: for `mode` in `{atomic, coupled-pair}` and `placement` in `{cores, spread}`, at the largest tested thread count, strides `8,16,32,64,128` against `256` (`m = 5`); Holm at family-wise `alpha = 0.01` per configuration; contended iff `p_holm <= 0.01` and `exp(mean_log_ratio) - 1 > 0.01` (1% floor). Exploratory configs (`volatile`, `rw-asymmetric`, `smt-sibling`, `t < max`, stride `512`) emit estimates and descriptive `class`/`knee_bytes` in the exploratory table (`primary = false`). | UT-10 passes. |
| FR-12 | Noise gate & classification: `mde90` is computed as a fraction (`exp((t(B-1, 1-alpha/m) + t(B-1, 0.90)) * sd / sqrt(B)) - 1`, reported as `mde90_pct = 100 * mde90`). Config is `inconclusive` if sentinel `mde90(256_B) > 0.10` (`> 0.05` with `--strict-h1`). `knee = s*` is the smallest uncontended stride such that every stride `s > s*` is uncontended. Classes: `flat`, `line64` (`s* <= 64`), `pair128` (`s* == 128`), `wider` (`s* >= 256`, e.g., `128` contended), `irregular` (non-monotone contention or significant `512 < 256` speedup, emitting `log.warning("faster-wider detected at stride %d; not a knee", s)` and `knee_bytes = null`), `inconclusive`. Sentinel also checks `drift_alert` (two-sided zero-mean `p <= 0.01` or `|r1| > 2 / sqrt(B)`). | UT-10 passes. |
| FR-13 | Built-in simulations `ST-01` to `ST-03` (`make test-sim`) validate the decision procedure by generating raw `y(s,b)`/`y(256,b)` latencies through production `stats.py` and `classify.py`. | `make test-sim` passes. |
| FR-14 | `--compare-folklore` joins each measured knee against all 7 ecosystems in `data/folklore.toml` (`crossbeam_utils`, `folly`, `hotspot_jvm`, `go_runtime`, `linux_kernel`, `cpp17`, `cpython_qsbr`); every entry stores `url`, `version` (or `commit`), and `retrieval_date`. | UT-11 passes. |
| FR-15 | Never overwrite: `run_all.sh` writes `results/HOST-UTC/` and refuses existing directories unless `--force` is passed. | NT-05 passes. |
| FR-16 | Outputs: `raw.csv`, `meta.json`, `summary.json`, `summary.csv`, `report.md`, `env.log`, and `figs/curve_*.png` + `figs/sentinel_hist.png` (`figs/knee_by_machine.png` is generated by Phase 2 `atlas`). | IT-01 passes. |
| FR-17 | *(Phase 2, post-G1)* Optional oracle `scripts/c2c_check.sh` records `perf c2c` HITM counts in `atomic` mode at stride 8 vs 256 and stores a JSON sidecar `[3]`. | IT-06 passes or prints `'skipped'`. |
| FR-18 | *(Phase 2, post-G1)* Optional MSR ablation `scripts/msr_ablate.sh`: `--intel` toggles MSR `0x1A4` bit 1 `[42]`; `--amd` toggles MSR `0xC0000108` on Zen 4/5 only (exiting `0` with `"MSR 0xC0000108 not supported on this CPU; Zen 4/5 only"` on Zen 2/unsupported). Dry-run by default, `--confirm` and root required, `trap` restore-on-exit mandatory, never called from default path. | IT-07 passes. |
| FR-19 | *(Phase 2, post-G1)* `make submit-bundle` validates and packages a run under `data/ARCH-CPU-UTC/` for community contribution. | Validator workflow passes. |

### 6. Non-Functional Requirements

| ID | Requirement | Target |
| :--- | :--- | :--- |
| NFR-01 Runtime | Default sweep (`B = 30`, 31 blocks, 8 cells/config, 52 ms/cell). At 4 cores (`cores` placement: `atomic` + `volatile` at 1,2,4 + `coupled-pair` at 4 = 7 configs = 56 cells/block -> 1,736 cells = ~90 s; adding `smt-sibling` adds ~48 s). At 16 cores (`cores` only: 13 configs -> 3,224 cells = ~2.8 min; adding `smt-sibling` ~4.3 min). | <= 10 min on 4 cores and <= 15 min on 16 cores; CI records actual wall time. |
| NFR-02 Analysis speed | `analyze` on a default run. | < 10 s on a laptop. |
| NFR-03 Portability | Linux x86-64 and AArch64; GCC >= 14.4 and Clang >= 22.1.8; `libgomp` or `libomp` `[32]`. macOS and Windows unsupported. | CI green on both architectures. |
| NFR-04 Repeatability & Determinism | Software build/analysis determinism (`make all` regenerates identical tables/figures from identical `raw.csv`) and measurement repeatability. | Identical `summary.json` from fixed CSV; same class in 3 of 3 repeat runs (`IT-03`). |
| NFR-05 Statistical reporting completeness | Every reported effect has simultaneous 99% bounds; every config reports `mde90_pct`, `gate`, `drift_alert`, and `shared_host` flag; exploratory results are labeled. | Report generator fails otherwise. |
| NFR-06 Code-size budget | Auditable core implementation. | <= 400 lines of C (`src/`) and <= 600 lines of Python (`analysis/fs_stride_analysis/`), excluding tests, enforced as a hard `cloc` fail in `ci.yml`. |
| NFR-07 Safety | No network access at runtime; no root in the default path; privileged scripts are opt-in Phase 2 sidecars. | Default path runs as an unprivileged user. |
| NFR-08 Limitations | Generated `report.md` lists: write-only counter pattern, `atomic` vs `volatile` store-buffer caveat, architecture coverage, VM noise, unknown BIOS prefetcher state, real-program heap adjacency, and actual `n` + machine count. | Section present in `report.md`. |
| NFR-09 Static quality | Compile with `-O2 -fopenmp -std=c11 -Wall -Wextra -Werror` (`_GNU_SOURCE` defined); run C unit tests under ASan and UBSan. | CI green. |
| NFR-10 Authorship disclosure | `docs/AUTHORSHIP.md` records AI-assisted parts and human-executed runs; AI-assisted commits carry `Assisted-by:`. | CI check passes. |

### 7. Risks & Mitigations

| Risk | Impact | Mitigation |
| :--- | :--- | :--- |
| **Contended chunk duration overshoot** | Under 30× contention, one `K = 65,536` chunk takes ~19 ms, pushing cell duration above 59 ms. | `UT-14` allows `50–100 ms` on dev machines and warns when `last_chunk_duration / cell_duration > 0.25`; sentinel `MDE90` catches high-variance cells. |
| **64-set L1D aliasing under `smt-sibling`** | On 64-set x86 cores, `threads * stride >= 4096` (e.g., `8t × 512 B`) wraps L1D sets and mixes set conflict with false sharing. | `check_stride` emits a `meta.json` warning whenever `threads * stride >= 4096`; `smt-sibling` is excluded from the primary family. |
| **Multi-socket / multi-CCD NUMA skew** | Cross-socket UPI/Infinity Fabric latency (~100+ ns) masks intra-socket L2 prefetcher effects (~10–20 ns). | `topo_pick` groups `coupled-pair` partners within the same `package_id`/LLC first; `spread` isolates cross-socket runs cleanly. |
| **AArch64 outline atomics (`UT-04`)** | Baseline ARMv8.0 builds emit `__aarch64_ldadd*_relax` calls instead of inline `ldadd`/`ldxr`. | Build AArch64 binary with `-mno-outline-atomics` (or match helper symbol in `UT-04`) and record flags in `meta.json`. |
| **High-core-count scaling (64–192t)** | Power-of-two sweeps up to 192 threads increase wall time and barrier overhead. | `run_all.sh` supports `THREADS_LIST` override; high-core Compile Farm runs execute in Phase 2 (`T19+`). |
| **MSR ablation / untrusted Phase 2 PR data** | Aborted `wrmsr` leaves prefetchers disabled; malicious `data/` PRs risk Markdown injection in `atlas.md`. | Phase 2 `msr_ablate.sh` uses `trap` on `EXIT INT TERM` and dry-run default; `validate-data.yml` validates schemas only without running untrusted code or pushing from PR context. |
| **Least-privilege `GITHUB_TOKEN`** | Excessive token scope on automated workflows increases supply-chain blast radius. | `ci.yml`, `measure.yml`, and `validate-data.yml` use `permissions: contents: read`; only tagged `release.yml` sets `contents: write`. |

### 8. Dependencies (Verified as of 27 Nov 2026)

Pinning policy: `analysis/requirements.lock` with hashes; GitHub Actions pinned to full commit SHAs with a version comment; Phase 2 `scripts/resolve_pins.sh` and Dependabot update pins accepting releases >= 14 days old `[38]`.

| Dependency | Version / Policy | Role | Status and Source |
| :--- | :--- | :--- | :--- |
| GCC | `16.2` (7 Aug 2026); `14.4` (19 Jun 2026) | Primary compiler | `[V]` `[14][15]`. CI tests 14.x and 16.x. |
| Clang / LLVM | `22.1.8` (16 Jun 2026); `23.1.6` (16–17 Nov 2026) | Second compiler, `libomp` | `[V]` `[16]`. |
| OpenMP runtime | `libgomp` or `libomp` | Thread spawn, barriers, `omp_get_wtime` | `[K]` `[32]`. |
| Python | `3.15.2` and `3.14.10` (25 Oct 2026); min `>= 3.12` | Analysis (`avoid 3.14.7–3.14.9, 3.15.0–3.15.1`) | `[V]` `[17]`. CI tests both. |
| NumPy | `2.5.5` (15 Nov 2026) | Arrays, paired math | `[V]` `[18]`. |
| SciPy | `1.18.1` (21 Aug 2026) | `scipy.stats.t`, `ttest_rel` | `[V]` `[19][36]`. |
| Matplotlib | `3.11.2` (11 Sep 2026) | Figures (`curve_*.png`, `sentinel_hist.png`) | `[V]` `[20]`. |
| pytest / ruff / jsonschema | `pytest 9.2.0`, `ruff 0.17.6`, `jsonschema` (locked in `requirements.lock`) | Tests, lint, schema checks | `[V]`/`[U]`. |
| pandas | Not used | Dropped (`D8`): stdlib `csv` + NumPy | n/a. |
| tomllib | Stdlib (Python 3.11+) | Reads `data/folklore.toml` | `[K]`. |
| shellcheck, clang-format, cloc | Distro packages | Shell/C lint, `cloc` gate | `[K]`. |
| `perf`, `msr-tools` (Phase 2) | Optional distro packages | `FR-17`, `FR-18` | `[3]`, `[K]`. |
| GitHub Actions | `actions/checkout@v7.0.1`, `actions/setup-python@v6.3.0`, `actions/upload-artifact@v7.0.2` (SHA-pinned) | Node 24 CI runners | `[V]` `[21][22][23]`. |
| Runner labels | `ubuntu-24.04`, `ubuntu-26.04`, `ubuntu-24.04-arm`, `ubuntu-26.04-arm` | CI matrix (never `ubuntu-latest`) | `[V]` `[24][25]`. |

### 9. Test Cases

#### Unit Tests (`tests/unit/`)

| ID | File / Target | Expected |
| :--- | :--- | :--- |
| UT-01 | `test_topo.sh` | Correct `cores`, `smt-sibling`, and `spread` CPU lists on fixture sysfs trees: SMT on, SMT off, hybrid P/E, dual-socket. E-cores excluded by default. |
| UT-02 | `test_alloc.c` | Base aligned to 4096; size is a multiple of 4096; memory zeroed (`ASan` + `UBSan`). |
| UT-03 | `test_layout.c` | At strides 8, 64, 128 with 4 slots (`uintptr_t`): stride 8 in one 64 B line; stride 64 in distinct 64 B lines with slots 0/1 in one 128 B chunk; stride 128 in distinct 128 B chunks. |
| UT-04 | `test_asm.sh` | `atomic` contains `lock` (x86-64) or `ldadd`/`ldxr` (AArch64 built with `-mno-outline-atomics`); `volatile` contains none; opcode recorded in `meta.json`. |
| UT-05 | `test_schedule.sh` | Same seed gives identical order; every block contains each cell once plus one sentinel per configuration; block 0 marked warm-up; `--sequential` disables shuffling. |
| UT-06 | `test_stats.py` | Exact 14 columns in `raw.csv`; `ns_per_op` equals `elapsed_s * 1e9 * threads / total_ops` within `1e-6`. |
| UT-07 | `test_stats.py` | `paired_t` matches `scipy.stats.ttest_rel` on fixed arrays; handles `sd == 0` guard. |
| UT-08 | `test_stats.py` | `holm` matches a hand-computed example. |
| UT-09 | `test_stats.py` | `mde90` formula matches a worked example (fraction internally, `_pct` on output) and Bonferroni `t.ppf(1 - 0.01/(2*m), B-1)`. |
| UT-10 | `test_classify.py` | Correct class for `flat`, `line64`, `pair128`, `wider`, `irregular` (including `512 < 256` warning), `inconclusive` (`> 0.10` and `--strict-h1` `> 0.05`). |
| UT-11 | `test_folklore.py` | All 7 entries in `data/folklore.toml` have `url`, `version` (or `commit`), and `retrieval_date`. |
| UT-12 | `test_stats.py` | `meta.json` validates against `schemas/meta.schema.json`; no key absent. |
| UT-13 | `test_stats.py` | `summary.json` validates against `schemas/summary.schema.json`. |
| UT-14 | `test_kernel.sh` | Cell duration at target 50 ms is between `50` and `100 ms` on the dev machine; warning only when `(last_chunk_duration / cell_duration) > 0.25` or on shared CI runners. |

#### Integration Tests (`tests/integration/`)

| ID | File / Target | Expected |
| :--- | :--- | :--- |
| IT-01 | `smoke.sh` | `make smoke` (2 strides, 2 thread counts, 5 blocks) ends with `report.md`, no traceback, under 60 s. |
| IT-02 | `repro.sh` | Full sweep produces a class for every configuration (primary and exploratory labeled), or `inconclusive` with reason. |
| IT-03 | `repro.sh` | Three full runs on the same machine: same class in 3 of 3; knee within one stride step. |
| IT-04 | `repro.sh` | Clang build produces identical schemas and `report.md`. |
| IT-05 | `repro.sh` | AArch64 build on `ubuntu-24.04-arm` executes full smoke/repro and validates schemas (never passes on `exit 3`; linear sysfs-absent VM fallback logged in `meta.json` if needed). |
| IT-06 | `oracle.sh` *(Phase 2)* | Optional bare-metal PMU check in `atomic` mode: `perf c2c` HITM counts at stride 8 vs 256 drop >= 5×; otherwise prints `'oracle disagrees'` without failing build (prints `'skipped'` if PMU unavailable). |
| IT-07 | `msr_dryrun.sh` *(Phase 2)* | `msr_ablate.sh` dry-run prints intended writes and changes nothing; Zen 2 / unsupported AMD exits `0` with unsupported message. |

#### Negative Tests (`tests/unit/` & `tests/integration/`)

| ID | Test | Expected |
| :--- | :--- | :--- |
| NT-01 | `analyze` with no `raw.csv` or required JSON | Exit 1, message `'run fs_stride first'`. |
| NT-02 | `raw.csv` missing a column | `ValueError` naming the missing column. |
| NT-03 | Threads list is only `1` | Warning; no knee reported (`knee_bytes = null`). |
| NT-04 | Threads above `P` without `--oversubscribe` | Exit 2. |
| NT-05 | Existing results directory without `--force` | Refuses (exit 2). |
| NT-06 | Stride `12` (or `--strides` omitting `256`) | Exit 2. |
| NT-07 | `coupled-pair` mode with `3` threads (or `2` threads) | Exit 2. |
| NT-08 | Run inside restricted `taskset` cpuset with too few CPUs | Exit 3. |

#### Statistical Validation (`analysis/fs_stride_analysis/sim.py`) & Empirical Gates

| ID | Test | Pass criterion |
| :--- | :--- | :--- |
| ST-01 | `2,000` synthetic null sweeps (`sim.py`); noise `sigma` in 1%, 2%, 3%; block correlation 0 and 0.3. | At least one primary false positive in <= 1.5% of sweeps (nominal 1%). |
| ST-02 | `1,000` synthetic sweeps (`sim.py`); 5% slowdown injected at **stride 64 only**. | Per-stride Holm detection power >= 90% at stride 64 for `sigma` up to 3%. |
| ST-03 | Spiky noise (`sim.py`): 8% of trials get an extra 20% latency spike. | ST-01 still holds (FWER <= 1.5%). |
| ST-04 | *(Empirical)* Random vs sequential (`--sequential`) trial order on one machine. | Both reported; random order shows smaller sentinel spread. |
| ST-05 | *(Empirical Gate)* Coverage. | Raw data from >= 3 machines before paper claims are drafted. |

*Rule:* If `ST-01` or `ST-02` fails, raise `B` instead of relaxing thresholds.

### 10. Expected Output

- **`raw.csv` (14 columns):** `run_id,host,mode,stride,threads,placement,block,order,role,total_ops,elapsed_s,ns_per_op,cpus,loadavg1` (`role` in `{ref, test, sentinel}`; `cpus` semicolon-delimited e.g. `0;1;2;3`).
- **`summary.json`:** Matches `schemas/summary.schema.json`. Per-cell fields: `mode, threads, placement, stride, role, n_blocks, mean_log_ratio, sd, effect_pct, ci99_low_pct, ci99_high_pct, p_raw, p_holm, primary, contended`. Per-config fields: `mode, threads, placement, primary, knee_bytes, class, mde90_pct, gate, drift_alert, reason`. Run-level `folklore` array.
- **`summary.csv` (mock, not measured; `None` serialized as `n/a`):**

| host | mode | threads | placement | mde90\_pct | knee\_bytes | class |
| :--- | :--- | :---: | :--- | :---: | :---: | :--- |
| laptop-x86 | coupled-pair | 4 | cores | 2.9 | 128 | pair128 |
| laptop-x86 | atomic | 4 | cores | 2.6 | 64 | line64 |
| cloud-vm | atomic | 4 | cores | 12.4 | n/a | inconclusive |

- **Terminal line (mock):** `mode=coupled-pair threads=4 placement=cores knee=128 B mde90=2.9% class=pair128 crossbeam(x86-64)=128 agree=yes`
- **Figures in `results/RUN/figs/`:** `curve_MODE_THREADS_PLACEMENT.png` (effect vs stride, log x-axis, simultaneous 99% bands, sentinel band shaded, knee marked), `sentinel_hist.png`. *(Phase 2 `atlas` generates `docs/figs/knee_by_machine.png`.)*
- **`report.md`:** Environment (`env.log`), metadata block, noise gate (`mde90_pct`, `drift_alert`) per config, primary results table, exploratory results table (labeled), 7-ecosystem folklore comparison, and Limitations section with actual `n` and machine count.

### 11. Environment Variables, Privileges, and External Accounts

`fs-stride` requires **no API keys**, accounts, or network access at runtime.

| Item | Required? | How supplied |
| :--- | :--- | :--- |
| `OMP_NUM_THREADS` | No | Env var; `--threads` overrides; effective value saved in `meta.json`. |
| `OMP_PROC_BIND`, `OMP_PLACES` | No (not used for pinning) | Recorded in `meta.json` if set; `sched_setaffinity` does all pinning (`FR-05`). |
| `TRIALS`, `THREADS_LIST` | No | Optional `run_all.sh` overrides (`TRIALS` defaults to `30`). |
| `perf` (`FR-17`, Phase 2) | Optional | Needs permissive `perf_event_paranoid` or `CAP_PERFMON`; AMD IBS (not Zen 3), Arm SPE `[3]`. |
| Root for MSR (`FR-18`, Phase 2) | Optional | `msr` module + root; dry-run default; `--confirm` required. |
| `GITHUB_TOKEN` | CI only | Provided by Actions (`contents: read` for CI/measure/validate; `contents: write` for Phase 2 `release.yml`). |
| GCC Compile Farm / Zenodo | Optional (Phase 2) | External account / UI only; no credentials in repo. |

---

## Part B: Implementation & Engineering Specification

### 12. Function Definitions & CLI Contract

#### C Modules: `src/` (5 Files: `main.c`, `topo.c`, `alloc.c`, `kernel.c`, `fs_stride.h`)

| File | Function | Signature | Responsibility |
| :--- | :--- | :--- | :--- |
| `main.c` | `main` | `int main(int argc, char **argv)` | Parse args, load topology, build schedule, run cells, write 14-col CSV, return exit `0..3`. |
| `main.c` | `parse_args` | `int parse_args(int argc, char **argv, config_t *cfg)` | Validate `--modes`, `--strides`, `--threads`, `--placements`, `--target-ms`, `--blocks`, `--seed`, `--sequential`, `--oversubscribe`, `--print-layout`, `--print-meta`, `--sysfs-root`. |
| `main.c` | `make_schedule` | `void make_schedule(cell_t *cells, size_t n_per_block, unsigned int seed, int blocks, int sequential)` | `splitmix64` Fisher-Yates shuffle per block (unless `sequential`); 1 `256_B` sentinel per config per block; block 0 warm-up. |
| `main.c` | `emit_row` | `void emit_row(const config_t *cfg, const cell_t *cell, const result_t *res)` | Write one 14-column `raw.csv` row (`cpus` semicolon-delimited). |
| `topo.c` | `topo_load` | `int topo_load(topo_t *topo, const char *sysfs_root)` | Parse `sysfs_root` (`core_cpus_list` / `thread_siblings_list`, `package_id`, P/E lists) intersected with `sched_getaffinity`. |
| `topo.c` | `topo_pick` | `int topo_pick(const topo_t *topo, fs_placement_t placement, fs_mode_t mode, int threads, int oversubscribe, int *cpus_out)` | Select CPUs for `cores`, `smt-sibling`, or `spread`; keep `coupled-pair` partners on distinct intra-socket/LLC cores. |
| `topo.c` | `pin_to_cpu` | `int pin_to_cpu(int cpu)` | `sched_setaffinity` on calling thread; return error -> exit 3 `[41]`. |
| `topo.c` | `detect_line_size` | `size_t detect_line_size(const char *sysfs_root)` | Read sysfs `coherency_line_size`, fallback `sysconf(_SC_LEVEL1_DCACHE_LINESIZE)`, else 64 (reported only). |
| `alloc.c` | `alloc_counters` | `void *alloc_counters(size_t stride, int slots)` | `posix_memalign(&ptr, 4096, round_up_4096(raw))`, `memset`, `atomic_init` `[40]`. |
| `alloc.c` | `check_stride` | `int check_stride(size_t stride, int max_threads, int *warn_aliasing_out)` | Reject non-multiples of 8 (exit 2); set aliasing warning flag when `max_threads * stride >= 4096`. |
| `kernel.c` | `run_cell` | `result_t run_cell(fs_mode_t mode, size_t stride, int threads, const int *cpus, double target_s)` | Pin threads, `barrier -> t_start -> K = 65,536 ops -> barrier -> check elapsed >= target_s`, sum `total_ops`, compute `ns_per_op = elapsed_s * 1e9 * threads / total_ops`. |
| `kernel.c` | `print_layout` | `void print_layout(const void *base, size_t stride, int slots)` | Print slot addresses with 64 B line and 128 B chunk indices (`--print-layout`). |

#### Python Package: `analysis/fs_stride_analysis/`

| Module | Function | Signature | Responsibility |
| :--- | :--- | :--- | :--- |
| `io.py` | `load_raw` | `(path: Path) -> list[dict]` | Read CSV via `csv`; validate 14 columns & `raw.schema.json` constraints (`ValueError` on missing column); drop `block == 0`. |
| `io.py` | `load_meta` | `(path: Path) -> dict` | Validate `meta.json` against `schemas/meta.schema.json`. |
| `stats.py` | `log_ratios` | `(rows: list[dict], config: tuple) -> tuple[dict[int, np.ndarray], np.ndarray]` | Return `(ratios_by_stride, sentinel_ratios)` for `ln(y(s,b)/y(256,b))`. |
| `stats.py` | `paired_t` | `(d: np.ndarray) -> tuple[float, float, float, float]` | One-sided paired t (`scipy.stats.t.sf`) `[36]` with explicit `sd == 0` guard; returns `(mean, sd, t, p_one_sided)`. |
| `stats.py` | `holm` | `(pvals: list[float]) -> list[float]` | Holm step-down adjusted p-values. |
| `stats.py` | `mde90` | `(sd: float, B: int, m: int, alpha: float) -> float` | Return fraction `exp((t(B-1, 1-alpha/m) + t(B-1, 0.90)) * sd / sqrt(B)) - 1`. |
| `stats.py` | `ci99_simultaneous` | `(mean: float, sd: float, B: int, m: int) -> tuple[float, float]` | Bonferroni `t.ppf(1 - 0.01/(2*m), B-1)` bounds converted to `%` via `(exp(b) - 1) * 100`. |
| `classify.py` | `knee` | `(contended: dict[int, bool]) -> tuple[int \| None, str]` | Smallest uncontended `s*` with all `s > s*` uncontended; handles `irregular` and `wider`. |
| `classify.py` | `classify_config` | `(summary: dict, gate: float = 0.10) -> str` | Apply `mde90 > gate` (`0.05` under `--strict-h1`), `512 < 256` warning -> `irregular`, and class rules. |
| `sim.py` | `simulate_sweep` | `(sigma: float, rho: float, effect: float, B: int, seed: int, spike_rate: float = 0.0) -> dict` | Generate raw `y(s,b)`/`y(256,b)` latencies (plus `ST-03` spikes) and evaluate via `stats.py` + `classify.py`. |
| `sim.py` | `run_st01_st03` | `() -> bool` | Execute `ST-01` (2,000 sweeps), `ST-02` (1,000 sweeps, stride 64), `ST-03` and print pass/fail. |
| `folklore.py` | `load_folklore` | `(path: Path) -> dict` | Parse `data/folklore.toml` via `tomllib`. |
| `folklore.py` | `compare` | `(summary: dict, folklore: dict, arch: str) -> list[dict]` | Join measured knees to all 7 ecosystems. |
| `report.py` | `make_figures` | `(summary: dict, outdir: Path) -> None` | Write `curve_*.png` and `sentinel_hist.png`. |
| `report.py` | `write_report` | `(summary: dict, meta: dict, env_log: str, outdir: Path) -> None` | Write `report.md` (with `env.log` & Limitations), `summary.json`, `summary.csv`. |
| `cli.py` | `main` | `() -> int` | Subcommands `analyze <dir> [--compare-folklore] [--strict-h1]` and `sim`; exit codes `0` (ok), `1` (missing `raw.csv`/required JSON), `2` (bad CLI arg), `3` (affinity failure). |

#### Shell Scripts: `scripts/`

| Script | Phase | Responsibility |
| :--- | :---: | :--- |
| `scripts/run_all.sh` | MVP | Build, sweep, analyze, report; refuses overwrite without `--force`; logs `env.log`. |
| `scripts/capture_meta.sh` | MVP | Collect `meta.json` (`lscpu`, kernel, governor, SMT, P/E lists, hypervisor, `shared_host`, compiler, `atomic_opcode`, `OMP_*`, warnings). |
| `scripts/c2c_check.sh` | Phase 2 | Optional `perf c2c` HITM oracle in `atomic` mode `[3]`. |
| `scripts/msr_ablate.sh` | Phase 2 | Optional Intel `0x1A4` bit 1 (`--intel`) and AMD Zen 4/5 `0xC0000108` (`--amd`) ablation; dry-run default; `--confirm` + `trap` restore. |
| `scripts/resolve_pins.sh` | Phase 2 | Look up releases >= 14 days old and update lockfile / action SHAs. |
| `scripts/license_check.sh` | Phase 2 | Query GitHub license API (with `--offline` fallback) for Section 15 neighbors. |

### 13. Project Tree (`Create` / `Exist` Status)

```text
fs-stride/
  AGENTS.md  README.md                                    [Existing]
  LICENSE  NOTICE  CITATION.cff  CHANGELOG.md  CONTRIBUTING.md  Makefile   [Create in Phase 1/2]
  src/
    fs_stride.h                                           [Created — contract]
    main.c  topo.c  alloc.c  kernel.c                     [Create — Block 1]
  analysis/
    pyproject.toml  requirements.lock                     [Create — Block 2]
    fs_stride_analysis/
      __init__.py  io.py  stats.py  classify.py  sim.py  folklore.py  report.py  cli.py  [Create — Block 2]
  schemas/
    raw.schema.json  meta.schema.json  summary.schema.json [Created — contract]
  scripts/
    run_all.sh  capture_meta.sh                           [Create — Block 1/3]
    c2c_check.sh  msr_ablate.sh  resolve_pins.sh  license_check.sh  [Create — Phase 2]
  tests/
    unit/         test_layout.c  test_alloc.c  test_topo.sh  test_asm.sh  test_schedule.sh  test_kernel.sh  test_stats.py  test_classify.py  test_folklore.py  [Create — Block 1/2]
    integration/  smoke.sh  repro.sh  oracle.sh  msr_dryrun.sh  [Create — Block 1/2/Phase 2]
    fixtures/     sysfs_smt_on/  sysfs_smt_off/  sysfs_hybrid/  sysfs_dual_socket/  synthetic/  [Create — Block 1/2]
  data/
    folklore.toml                                         [Created — contract]
    ARCH-CPU-UTC/                                         [Pilot in MVP; community PRs in Phase 2]
  results/                                                [Generated, git-ignored except .gitkeep]
  docs/
    RESEARCH_PLAN.md  fs-stride Complete Project Specification v2.0.md  [Existing — updated]
    decisions.md  related-work.md  AUTHORSHIP.md          [Created]
    method.md  limitations.md  atlas.md                   [Create — Block 2/Phase 2]
  paper/          main.tex  refs.bib                      [Create — Phase 2]
  .github/
    workflows/    ci.yml  measure.yml                     [Create — MVP Block 2]
                  release.yml  validate-data.yml          [Create — Phase 2]
    dependabot.yml  PULL_REQUEST_TEMPLATE.md  ISSUE_TEMPLATE/  [Create — Phase 1/2]
```

### 14. Git Commit, PR, and CI Standards

- **Commits:** Conventional Commits 1.0.0 `[33]` (`type(scope): summary`, <= 72 chars, imperative). Types: `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `ci`, `build`, `chore`, `data`. Scopes: `bench`, `topo`, `alloc`, `kernel`, `analysis`, `stats`, `classify`, `sim`, `folklore`, `report`, `cli`, `scripts`, `ci`, `docs`, `data`, `paper`. Require `git commit -s` (DCO `[34]`) and `Assisted-by:` trailer for AI-written code.
- **PR rules:** `<= 400` changed lines excluding data/generated files; 1 reviewer for `docs`/`ci`/`test`/`data`, **2 reviewers** for frozen invariants (`src/kernel.c`, `src/main.c`, `src/alloc.c`, `stats.py`, `classify.py`, `sim.py`, `io.py`, `run_all.sh`, `data/folklore.toml`, `paper/main.tex`).
- **CI Workflows:**
  - `ci.yml` *(MVP)*: `permissions: contents: read`; GCC 14/16 & Clang 22/23 `-Werror`; `ruff`, `shellcheck`, `clang-format`; `cloc` hard-fail (`<= 400 C`, `<= 600 Python`); ASan/UBSan unit tests; `make test-asm`; `make test-sim`; DCO & Conventional Commits; `make smoke`; schema validation; upload smoke report.
  - `measure.yml` *(MVP weekly, non-gating)*: `permissions: contents: read`; run `make sweep` on `ubuntu-24.04`, `ubuntu-26.04`, `ubuntu-24.04-arm`, `ubuntu-26.04-arm` to collect H3 cloud-VM noise data.
  - `validate-data.yml` & `release.yml` *(Phase 2, post-G1)*: `validate-data.yml` (`permissions: contents: read`) checks incoming `data/` bundles and verifies `docs/atlas.md` freshness without pushing commits from PR context; `release.yml` (`permissions: contents: write`) builds `fs-stride-vX.Y.Z.tar.gz` + `SHA256SUMS` on `v*` tags.

### 15. Existing GitHub Projects and Reuse Boundaries

No existing public repository implements a cross-machine stride sweep with within-block paired statistics and an `MDE90` noise floor `[U]`. Nearest neighbors are documented strictly as design references (no code copied): `khale/false-sharing` `[27]` (no license file), `joemario/perf-c2c-usage-files` `[28]` (license unconfirmed), `perfgo/examples/false-sharing` `[29]` (Apache-2.0), `crossbeam-utils` `[2]` (MIT OR Apache-2.0), `facebook/folly` (Apache-2.0), Linux `perf c2c` `[3][4]`, `plasma-umass` Sheriff/Stabilizer `[30]` (GPL-2.0 / unverified), and `efeslab/huron` `[13]` (public on GitHub, no license statement in README).

### 16. Build Backlog

#### Phase 1: MVP (`T00–T13`)
| ID | Deliverable | Verified by |
| :--- | :--- | :--- |
| T00 | Repo bootstrap: `LICENSE`, `Makefile`, hooks, `.gitignore` | `make lint` |
| T01 | `src/topo.c` + sysfs fixtures | `UT-01` |
| T02 | `src/alloc.c` | `UT-02` (ASan/UBSan) |
| T03 | `src/kernel.c` | `UT-03`, `UT-04`, `UT-14` |
| T04 | `src/main.c`: CLI, schedule, 14-col CSV | `UT-05`, `UT-06`, `NT-04`–`NT-08` |
| T05 | `scripts/capture_meta.sh` + schema checks | `UT-12` |
| T06 | `analysis/fs_stride_analysis/io.py` | `NT-01`, `NT-02` |
| T07 | `analysis/fs_stride_analysis/stats.py` | `UT-07`–`UT-09` |
| T08 | `analysis/fs_stride_analysis/sim.py` | `ST-01`–`ST-03` (`make test-sim`) |
| T09 | `analysis/fs_stride_analysis/classify.py` | `UT-10` |
| T10 | `data/folklore.toml` (verified) + `folklore.py` | `UT-11` |
| T11 | `analysis/fs_stride_analysis/report.py` + `cli.py` | `UT-13`, `IT-01`, `NT-01`, `NT-03` |
| T12 | `scripts/run_all.sh`, `make smoke`, `make sweep` | `IT-01`, `IT-02`, `NT-05` |
| T13 | Local pilot run, commit pilot bundle to `data/` | Gates `G0`, `G1`, `G2` |

#### Phase 2: Post-Gate G1 (`T14–T20`)
| ID | Deliverable | Verified by |
| :--- | :--- | :--- |
| T14 | `scripts/c2c_check.sh` | `IT-06` |
| T15 | `scripts/msr_ablate.sh` | `IT-07` |
| T16 | `release.yml`, `validate-data.yml`, `make submit-bundle` | Green workflow on test branch |
| T17 | `scripts/resolve_pins.sh`, `dependabot.yml` | Dry run prints diff |
| T18 | `scripts/license_check.sh` | Prints license or `'none'` per repo |
| T19 | `docs/atlas.md` + `knee_by_machine.png` generator + Compile Farm runs | Golden test + `ST-05` (`G3`) |
| T20 | `paper/main.tex`, `docs/method.md`, `docs/limitations.md` | `make paper` builds |

### 17. Gates and Pilot

| Gate | When | Pass criteria | If it fails |
| :--- | :--- | :--- | :--- |
| G0 kernel sanity | After T04 | On dev machine, `atomic` at 2 threads (`cores`) is >= 1.5× slower at stride 8 than 256, and `cpus` matches intended CPUs. | Debug pinning, SMT, VM; do not continue. |
| G1 noise | T13 | Sentinel `mde90 <= 0.10` (`10%`) for >= 80% of primary configs. | Pivot headline claim to H3 noise envelope. |
| G2 controls | T13 | `volatile`, `rw-asymmetric`, and `coupled-pair` recorded either way. | Report as observed. |
| G3 coverage | Before drafting claims | Raw data from >= 3 machines (`ST-05`). | State limited coverage in abstract. |

### 18. Known Unknowns

- Whether `coupled-pair` shows a 64 B vs 128 B difference on bare-metal Intel hardware; empirical data settles it.
- Whether `volatile` masking reproduces on bare metal across generations.
- Exact behavior of `coupled-pair` on non-Intel/non-AMD Compile Farm hosts (POWER10, s390x, RISC-V).
- Whether prior literature includes a systematic cross-machine padding study (requires full literature survey before stating novelty in `paper/main.tex`).

### 19. References

1. Jayasena et al., Detection of False Sharing Using Machine Learning, SC'13. <https://commit.csail.mit.edu/papers/2013/falsesharing-sc13.pdf> `[V]`
2. crossbeam-utils `CachePadded` source. <https://docs.rs/crossbeam-utils/latest/src/crossbeam_utils/cache_padded.rs.html> `[V]`
3. `perf-c2c(1)`. <https://man7.org/linux/man-pages/man1/perf-c2c.1.html> `[V]`
4. Linux `perf c2c` double-cacheline option (Feng Tang, Feb 2023). <https://lore.kernel.org/r/20230214075823.246414-1-feng.tang@intel.com> `[V]`
5. JVM `@Contended` padding. <https://dzone.com/articles/what-false-sharing-is-and-how-jvm-prevents-it> `[V]`
6. cppreference, `hardware_destructive_interference_size`. <https://en.cppreference.com/w/cpp/thread/hardware_destructive_interference_size> `[V]`
7. Stack Overflow 72126606 (mirror). <https://kiwix.lema.org/stackoverflow.com_en_all_2023-11/questions/72126606/should-the-cache-padding-size-of-x86-64-be-128-bytes> `[V]`
8. Mechanical Sympathy, Prefetching and false sharing. <https://groups.google.com/g/mechanical-sympathy/c/i3-M2uCYTJE> `[V]`
9. CPython `gh-144438` patch. <https://github.com/python/cpython/pull/144554.patch> `[V]`
10. Liu and Berger, SHERIFF, OOPSLA 2011. <https://people.cs.umass.edu/~emery/pubs/res005-liu.pdf> `[V]`
11. Liu et al., PREDATOR, PPoPP 2014. <https://people.cs.umass.edu/~emery/pubs/Predator-ppopp14.pdf> `[V]`
12. Liu and Liu, Cheetah, CGO 2016. <https://core.ac.uk/download/235418437.pdf> `[V]`
13. Khan et al., Huron, PLDI 2019 (`efeslab/huron`). <https://homes.cs.washington.edu/~baris/public/huron.pdf> `[V]`
14. GCC 16 and GCC 14 release pages. <https://gcc.gnu.org/gcc-16/> and <https://gcc.gnu.org/gcc-14/> `[V]`
15. GCC 16.2 coverage. <https://phoronix.com/news/GCC-16.2-Released> `[V]`
16. LLVM site and LLVM 22 coverage. <https://llvm.org/> and <https://phoronix.com/news/llvm-clang-22.1-released> `[V]`
17. Python downloads and 3.15.0 release. <https://www.python.org/downloads/> `[V]`
18. NumPy releases. <https://github.com/numpy/numpy/releases> `[V]`
19. SciPy releases. <https://github.com/scipy/scipy/releases> `[V]`
20. Matplotlib releases. <https://github.com/matplotlib/matplotlib/releases> `[V]`
21. `actions/checkout` releases. <https://github.com/actions/checkout/releases> `[V]`
22. `actions/upload-artifact` and `actions/setup-python` releases. <https://github.com/actions/upload-artifact/releases> and <https://github.com/actions/setup-python/releases> `[V]`
23. Node 20 removal from Actions runners. <https://github.blog/changelog/2026-09-24-node-20-is-no-longer-available-in-github-actions/> `[V]`
24. GitHub-hosted runners. <https://docs.github.com/en/actions/reference/runners/github-hosted-runners> `[V]`
25. Ubuntu 26 GA and latest migration. <https://github.blog/changelog/2026-09-17-ubuntu-26-generally-available-and-latest-migration> `[V]`
26. `actions/runner-images` releases. <https://github.com/actions/runner-images/releases> `[V]`
27. `khale/false-sharing`. <https://github.com/khale/false-sharing> `[V]`
28. `joemario/perf-c2c-usage-files`. <https://github.com/joemario/perf-c2c-usage-files> `[V]`
29. `perfgo` false-sharing example. <https://pkg.go.dev/github.com/perfgo/perfgo/examples/false-sharing> `[V]`
30. PLASMA group software (Sheriff, Stabilizer). <https://people.cs.umass.edu/~emery/plasma/emery/plasma.html> `[V]`
31. GCC Compile Farm. <https://gcc.gnu.org/wiki/CompileFarm> and <https://portal.cfarm.net/users/new/> `[V]`
32. OpenMP specifications. <https://www.openmp.org/specifications/> `[K]`
33. Conventional Commits 1.0.0. <https://www.conventionalcommits.org/en/v1.0.0/> `[K]`
34. Developer Certificate of Origin. <https://developercertificate.org/> `[K]`
35. Semantic Versioning. <https://semver.org/> `[K]`
36. SciPy statistics reference (`ttest_rel`, `t`). <https://docs.scipy.org/doc/scipy/reference/stats.html> `[K]`
37. Benchmarking methodology: Georges, Buytaert, and Eeckhout, OOPSLA 2007 (DOI `10.1145/1297027.1297033`); Mytkowicz et al., ASPLOS 2009 (DOI `10.1145/1508284.1508275`); Kalibera and Jones, ISMM 2013 (DOI `10.1145/2464157.2464160`) `[V]`
38. Dependabot documentation. <https://docs.github.com/en/code-security/dependabot> `[K]`
39. GitHub token and releases documentation. <https://docs.github.com/en/actions/security-for-github-actions/security-guides/automatic-token-authentication> `[K]`
40. `posix_memalign(3)`. <https://man7.org/linux/man-pages/man3/posix_memalign.3.html> `[K]`
41. `sched_setaffinity(2)`. <https://man7.org/linux/man-pages/man2/sched_setaffinity.2.html> `[K]`
42. Intel Software Developer Manuals (MSR `0x1A4` prefetcher control). <https://www.intel.com/content/www/us/en/developer/articles/technical/intel-sdm.html> `[K]`
43. Keep a Changelog. <https://keepachangelog.com/> `[K]`
