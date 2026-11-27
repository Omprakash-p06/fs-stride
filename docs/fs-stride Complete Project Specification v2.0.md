# fs-stride: Complete Project Specification v2.0

Measuring the effective false-sharing distance of CPUs. 27 November 2026. This consolidates draft 1.0 and the v2.0 audit review into one specification. Part A (sections 1 to 8) is below; part B (sections 9 to 17) follows.

Tags: **\[V\]** checked against a source during research; **\[K\]** general knowledge, verify before citing; **\[U\]** unverified or taken only from your audit; **\[R\]** my own arithmetic or reasoning, not executed. Numbers in brackets like \[3\] point to section 17. Every sample number in section 7 is a mock-up, not a measurement.

## 1. Project Name

- **Name:** fs-stride
- **Subtitle:** A reproducible stride-sweep benchmark and paired-statistics analysis for the effective false-sharing distance of CPUs.
- **Slugs:** repo `fs-stride`; C binary `fs_stride`; Python package `fs_stride_analysis`.
- **License:** MIT for original code. No code is copied from other repositories (see section 13); anything reused later is listed in `NOTICE` with its upstream license.

## 2. Project Purpose

**Problem.** Programmers pad per-thread data to avoid false sharing, but the right distance is argued from folklore. crossbeam pads 128 B on x86-64, aarch64 and powerpc64, 256 B on s390x, 32 B on arm and some mips and riscv targets (it varies by version), and 64 B elsewhere \[2\]. The JVM `@Contended` default is 128 B \[5\]. The C++ reference example falls back to 64 B on x86-64 \[6\]. Linux `perf c2c` has an option that treats adjacent line pairs together because of the L2 spatial prefetcher \[3\]\[4\]. One Stack Overflow microbenchmark found no 64 B vs 128 B difference while an expert replied it was not designed to test prefetcher effects \[7\]; related discussion is in \[8\]. Real software is still affected: CPython gh-144438 (Feb 2026) fixed false sharing between the QSBR array and a thread-state field by aligning to 64 B \[9\]. Counter-based tools (SC'13 classifier \[1\], Sheriff \[10\], Predator \[11\], Cheetah \[12\], Huron \[13\]) answer a different question: where false sharing occurs, not how far apart data must be.

**Course link.** The syllabus Unit 4 covers caches, cache coherence and false sharing in OpenMP; Unit 2 covers speedup, scalability and taking timings of parallel programs. This project extends both.

**Product.** A small C benchmark plus a Python analysis pipeline that, on any Linux machine, sweeps the byte distance between per-thread counters, measures noise inside the same run, and reports the knee: the smallest distance beyond which more padding no longer helps, with intervals and an explicit 'inconclusive' verdict when the machine is too noisy. No hardware counters, no root in the default path.

**Hypotheses (falsifiable).**

- **H1:** on Intel x86-64 with the L2 adjacent-line prefetcher enabled, the pair-mode kernel is slower at 64 B spacing than at 128 B spacing beyond the noise floor. (Open: \[7\] disagrees with the folklore in \[2\]\[8\].)
- **H2:** the knee equals 64 B on parts with 64 B coherency granularity and 128 B on parts with 128 B granularity (for example Apple silicon, per \[2\]).
- **H3:** on shared cloud VMs the noise gate returns 'inconclusive' for a measurable fraction of configurations.
- **H4:** plain-store (volatile) false sharing can be masked relative to atomic read-modify-write. This claim currently rests on one unverified blog post \[U\]; it is tested, not assumed.

**Contributions.** (a) The tool with a paired-block decision rule and a measured noise floor; (b) a public table of measured knees across at least 3 machines compared with the constants in \[2\]\[5\]\[6\]; (c) raw data and a one-command rerun.

**Non-goals.** Not a profiler and not a detector for arbitrary programs (use \[3\]\[10\]\[11\]\[12\]); not a claim that padded-vs-unpadded timing is new, since it is existing practice \[29\]; atomics are not claimed to represent typical real code.

## 3. Functional Requirements

| ID | Requirement | Machine-checkable acceptance |
| --- | --- | --- |
| FR-01 | Modes: `atomic` (relaxed fetch\_add on a private counter), `volatile` (plain read-modify-write control), `pair` (threads 2k and 2k+1 share one atomic counter at slot k). | UT-03, UT-04 pass. |
| FR-02 | Strides default to 8,16,32,64,128,256,512 B; stride 256 is the reference; any list via `--strides`. Strides must be multiples of 8; warn at 4096 or above. | NT-06 passes. |
| FR-03 | Counter buffer from `posix_memalign` with 4096 alignment, size rounded up to a multiple of 4096, zeroed before each cell \[40\]. | UT-02 passes. |
| FR-04 | Thread counts default to 1,2,4,...,P (P = physical cores in the selected CPU set); more than P rejected without `--oversubscribe`; pair mode only for even counts of at least 4. | NT-04, NT-07 pass. |
| FR-05 | Each thread pins itself inside the OpenMP parallel region with `sched_setaffinity`, using CPUs chosen from sysfs topology; placements `cores` (one thread per physical core) and `smt` (siblings paired); `sched_getcpu()` recorded per thread; exit code 3 on failure \[41\]. | UT-01, NT-08 pass. |
| FR-06 | Hybrid CPUs: default to P-cores only; log P-core and E-core CPU lists. | UT-01 hybrid fixture passes. |
| FR-07 | Each cell runs `--target-ms` (default 50); threads loop in chunks of 1,024 operations and read a shared stop flag on its own 256 B-aligned struct; thread 0 sets the flag; no calibration phase and no per-chunk barrier. `ns_per_op = elapsed_s * 1e9 * threads / total_ops`. | UT-06, UT-14 pass. |
| FR-08 | Blocks of one seeded random permutation of all cells plus a second measurement of stride 256 (sentinel); block 0 discarded; default B = 30. | UT-05 passes. |
| FR-09 | `meta.json` keys: cpu\_model, microarch, lscpu, kernel, governor, smt, p\_core\_cpus, e\_core\_cpus, sysfs\_coherency\_line\_size, hypervisor, loadavg\_start, compiler, cflags, atomic\_opcode, omp\_runtime, git\_sha, seed, shared\_host. Missing values are the string 'unknown'. | UT-12 passes. |
| FR-10 | Analysis computes paired log ratios against the same block's stride-256 reference, paired t statistics, Holm adjustment, effect sizes and 99% intervals. | UT-07 to UT-09 pass. |
| FR-11 | Primary family fixed in advance: for each mode in atomic and pair and each placement, at the largest tested thread count, strides 8,16,32,64,128 against 256; Holm at family-wise alpha 0.01; contended means adjusted p at most 0.01 and effect at least 2%. All other cells are exploratory (estimates only, no verdict). | UT-10 passes. |
| FR-12 | Noise gate: configuration is `inconclusive` if the sentinel MDE90 exceeds 10%. Classes: flat, line64, pair128, wider, irregular (significance not monotone in stride), inconclusive. | UT-10 passes. |
| FR-13 | Built-in simulations ST-01 to ST-03 validate the whole decision procedure. | `make test-sim` passes. |
| FR-14 | `--compare-folklore` joins each measured knee with the constant assumed by crossbeam \[2\], the JVM \[5\] and C++ \[6\]; every entry in `data/folklore.toml` stores source URL, commit or version, and retrieval date. | UT-11 passes. |
| FR-15 | Never overwrite: each run writes `results/HOST-UTC/`; `--force` required to reuse a directory. | NT-05 passes. |
| FR-16 | Outputs: `raw.csv`, `meta.json`, `summary.json`, `summary.csv`, `report.md`, figures. | IT-01 passes. |
| FR-17 | Optional oracle `scripts/c2c_check.sh` records `perf c2c` at a small and a large stride and stores a sidecar \[3\]. | IT-06 passes or prints 'skipped'. |
| FR-18 | Optional Intel MSR ablation `scripts/msr_ablate.sh`: dry-run by default, explicit confirm flag, restores the original value on exit \[K: Intel SDM, MSR 0x1A4\]. | IT-07 passes. |
| FR-19 | `make submit-bundle` packages a validated run under `data/ARCH-CPU-UTC/` for community contribution. | Validator workflow passes. |

## 4. Non-Functional Requirements

| ID | Requirement | Target |
| --- | --- | --- |
| NFR-01 Runtime | Default sweep. Cells per block = 8 times the number of (mode, threads, placement) configurations \[R\]. 4 cores, placement cores: atomic and volatile at 1,2,4 plus pair at 4 = 7 configurations, 56 cells, 1,736 cells in 31 blocks, about 90 s at 52 ms per cell. 16 cores: 13 configurations, 3,224 cells, about 2.8 min. | At most 10 min on 4 cores and 15 min on 16 cores; CI records the actual figure. |
| NFR-02 Analysis speed | `analyze` on a default run. | Under 10 s on a laptop. |
| NFR-03 Portability | Linux x86-64 and AArch64; GCC and Clang; libgomp or libomp \[32\]. macOS and Windows unsupported (thread pinning differs). | CI green on both architectures. |
| NFR-04 Reproducibility | `make all` from a fresh clone regenerates every table and figure from raw data. | Same class in 3 of 3 repeat runs (IT-03). |
| NFR-05 Statistical honesty | Every reported effect has an interval; every run reports its noise gate and VM flag; exploratory results are labeled. | Report generator fails otherwise. |
| NFR-06 Size | Auditable code. | At most 400 lines of C and 600 lines of Python (excluding tests), enforced by `cloc` in CI. |
| NFR-07 Safety | No network access at run time; no root in the default path; privileged scripts are opt-in. | Default path runs as an unprivileged user. |
| NFR-08 Limitations | Generated report lists: write-only counter pattern, atomic vs plain-store caveat, architecture coverage, VM noise, unknown prefetcher BIOS state, heap adjacency in real programs not covered. | Section present with actual n and machine count. |
| NFR-09 Static quality | Compile with `-O2 -fopenmp -std=c11 -Wall -Wextra -Werror`; run unit tests under ASan and UBSan. | CI green. |
| NFR-10 Honesty of authorship | `docs/AUTHORSHIP.md` records AI-assisted parts and which results the author personally ran; commits carry an `Assisted-by:` trailer where applicable. | CI check passes. |

## 5. Dependencies (latest verified as of 27 Nov 2026)

Pinning policy: `requirements.lock` with hashes; GitHub Actions pinned to full commit SHAs with a version comment; `scripts/resolve_pins.sh` and Dependabot update both weekly, accepting only releases at least 14 days old \[38\].

| Dependency | Latest found | Role | Status and source |
| --- | --- | --- | --- |
| GCC | 16.2 (7 Aug 2026); 14.4 listed 26 Jun 2026 | Primary compiler | \[V\] \[14\]\[15\]. CI tests 14.x and 16.x. |
| Clang/LLVM | 22.1.8 (16 Jun 2026); 23.1.0 scheduled 25 Aug 2026, current 23.1.x point not confirmed | Second compiler, libomp | \[V\]/\[U\] \[16\] |
| OpenMP runtime | libgomp or libomp | Threads, `omp_get_wtime` | \[K\] \[32\] |
| Python | 3.15.0 (9 Oct 2026); 3.14.7 (5 Aug 2026) | Analysis | \[V\] \[17\]. Point releases after those not confirmed. CI tests both. |
| NumPy | 2.5.5 (15 Nov 2026), supports Python 3.12 to 3.15 | Arrays | \[V\] \[18\] |
| SciPy | 1.18 (June 2026); patch not confirmed | `scipy.stats.t`, `ttest_rel` | \[V\]/\[U\] \[19\]\[36\] |
| Matplotlib | 3.10.9 seen May 2026; newer not confirmed | Figures | \[V\]/\[U\] \[20\] |
| pytest, ruff, jsonschema | not verified | Tests, lint, schema checks | \[U\]; pinned by `resolve_pins.sh` |
| pandas | not used | Dropped (D8): stdlib `csv` plus NumPy | n/a |
| tomllib | standard library (Python 3.11+) | Reads `folklore.toml` | \[K\] |
| shellcheck, clang-format, cloc | distro packages | Lint, line budget | \[K\] |
| perf (optional) | matches kernel | Oracle for FR-17 | \[3\] |
| msr-tools (optional) | distro package | FR-18 | \[K\] |
| actions/checkout | v7.0.1 (17 Jul 2026) | CI | \[V\] \[21\] |
| actions/upload-artifact | v7 line (7.0.1 seen) | CI | \[V\] \[22\] |
| actions/setup-python | v7 line (seen in Sep 2026 pin lists) | CI | \[V, weak\] \[22\] |
| Runner labels | `ubuntu-24.04`, `ubuntu-26.04` (GA 17 Sep 2026), `ubuntu-24.04-arm`, `ubuntu-26.04-arm` | CI | \[V\] \[24\]\[25\]. `ubuntu-latest` migration to 26.04 ran 19 Oct to 19 Nov 2026; name labels explicitly. |

Node 20 was removed from Actions runners on 23 Sep 2026, so only Node 24 based action releases work \[V\]\[23\]. Public repositories get standard runners free \[24\].

## 6. Test Cases

### Unit tests (`tests/unit/`)

| ID | Test | Expected |
| --- | --- | --- |
| UT-01 | Topology parser on fixture sysfs trees: SMT on, SMT off, hybrid P/E, dual-socket. | Correct `cores` and `smt` CPU lists; E-cores excluded by default. |
| UT-02 | Allocator. | Base aligned to 4096; size a multiple of 4096; memory zeroed. |
| UT-03 | Layout at strides 8, 64, 128 with 4 slots (use `uintptr_t`). | Stride 8: all in one 64 B line. Stride 64: distinct 64 B lines, slots 0 and 1 in one 128 B chunk. Stride 128: distinct 128 B chunks. |
| UT-04 | Disassembly of the kernel. | Atomic mode contains `lock` (x86-64) or `ldadd`/`ldxr` (AArch64); volatile contains none; opcode written to meta.json. |
| UT-05 | Schedule. | Same seed gives identical order; every block contains each cell once plus one sentinel. |
| UT-06 | CSV schema and metric. | Exact columns; `ns_per_op` equals `elapsed_s*1e9*threads/total_ops` within 1e-6. |
| UT-07 | Paired t implementation. | Matches `scipy.stats.ttest_rel` on fixed arrays. |
| UT-08 | Holm adjustment. | Matches a hand-computed example. |
| UT-09 | MDE90 formula. | Matches a worked example. |
| UT-10 | Classifier on golden synthetic datasets. | Correct class for flat, line64, pair128, wider, irregular, inconclusive. |
| UT-11 | `folklore.toml`. | Every entry has url, commit or version, and date. |
| UT-12 | `meta.json` against its schema. | Valid; no key absent. |
| UT-13 | `summary.json` against its schema. | Valid. |
| UT-14 | Cell duration at target 50 ms. | Elapsed between 50 and 59 ms on the dev machine (warning only on shared CI runners). |

### Integration tests (`tests/integration/`)

| ID | Test | Expected |
| --- | --- | --- |
| IT-01 | `make smoke` (2 strides, 2 thread counts, 5 blocks). | Pipeline ends with `report.md`, no traceback, under 60 s on the dev machine. |
| IT-02 | Full sweep and analysis. | A class for every configuration, or 'inconclusive' with reason. |
| IT-03 | Three full runs, same machine. | Same class in 3 of 3; knee within one stride step. |
| IT-04 | Clang build and run. | Same schemas; report generated. |
| IT-05 | AArch64 build and run on `ubuntu-24.04-arm`. | Same schemas, or pinning failure reported with exit 3. |
| IT-06 | Oracle (optional, bare metal with PMU support): `perf c2c` HITM counts at stride 8 vs 256. | At least a 5x drop; otherwise flag 'oracle disagrees'. |
| IT-07 | MSR ablation dry-run. | Prints intended writes; changes nothing. |

### Negative tests

| ID | Test | Expected |
| --- | --- | --- |
| NT-01 | Analyze with no raw data. | Exit 1, message 'run fs\_stride first'. |
| NT-02 | CSV missing a column. | `ValueError` naming the column. |
| NT-03 | Threads list is only 1. | Warning; no knee reported. |
| NT-04 | Threads above P without `--oversubscribe`. | Exit 2. |
| NT-05 | Existing results directory without `--force`. | Refuses. |
| NT-06 | Stride 12. | Exit 2. |
| NT-07 | Pair mode with 3 threads. | Exit 2. |
| NT-08 | Run inside a restricted cpuset (`taskset`) with too few CPUs. | Exit 3. |

### Statistical validation (`analysis/sim.py`)

| ID | Test | Pass criterion |
| --- | --- | --- |
| ST-01 | 2,000 synthetic null sweeps; noise sigma in 1%, 2%, 3%; block correlation 0 and 0.3. | At least one primary false positive in at most 1.5% of sweeps. |
| ST-02 | Same, with a 5% slowdown injected at stride 64 only. | Power at least 90% for sigma up to 3%. |
| ST-03 | Spiky noise: 8% of trials get an extra 20%. | ST-01 still holds. |
| ST-04 | Random vs sequential trial order on one machine. | Both reported; random order should show the smaller sentinel spread. |
| ST-05 | Coverage. | Raw data from at least 3 machines before claims are drafted. |

If ST-01 or ST-02 fails, raise B instead of relaxing the thresholds.

## 7. Expected Output

**`raw.csv` columns:** `run_id,host,mode,stride,threads,placement,block,order,role,total_ops,elapsed_s,ns_per_op,cpus,loadavg1` (role is ref, test or sentinel).

**`summary.json`:** per cell `mode, threads, placement, stride, n_blocks, mean_log_ratio, sd, effect_pct, ci99_low_pct, ci99_high_pct, p_raw, p_holm, primary, contended`; per configuration `knee_bytes, class, mde90_pct, gate`; run level `folklore` table.

**`summary.csv` (mock, not measured):**

| host | mode | threads | placement | mde90\_pct | knee\_bytes | class |
| --- | --- | --- | --- | --- | --- | --- |
| laptop-x86 | pair | 4 | cores | 2.9 | 128 | pair128 |
| laptop-x86 | atomic | 4 | cores | 2.6 | 64 | line64 |
| cloud-vm | atomic | 4 | cores | 12.4 | n/a | inconclusive |

**Terminal line (mock):** `mode=pair threads=4 placement=cores knee=128B mde90=2.9% class=pair128 crossbeam(x86-64)=128 agree=yes`.

**Figures in `results/RUN/figs/`:** `curve_MODE_THREADS_PLACEMENT.png` (effect vs stride, log x axis, 99% bands, sentinel band shaded, knee marked); `sentinel_hist.png`; `knee_by_machine.png`.

**`report.md`:** metadata block, noise gate per configuration, primary results table, exploratory results table (labeled), folklore comparison, Limitations section with actual n and machine count.

## 8. API Keys Documentation

fs-stride needs **no API keys**, accounts or network access at run time.

| Item | Required? | How it is supplied |
| --- | --- | --- |
| `OMP_NUM_THREADS` | No | Environment variable; CLI `--threads` overrides; effective value saved in `meta.json` \[32\]. |
| `OMP_PROC_BIND`, `OMP_PLACES` | No, not used for pinning | Pinning is done with `sched_setaffinity` (FR-05); if set, values are recorded only. |
| `perf` access (FR-17) | Optional | Needs a permissive `perf_event_paranoid` or `CAP_PERFMON`; AMD uses IBS and Zen 3 is unsupported; Arm needs SPE \[3\]. |
| Root for MSR writes (FR-18) | Optional | `msr` kernel module and root; script is dry-run by default \[K\]. |
| `GITHUB_TOKEN` | CI only | Provided automatically by Actions; release job sets `permissions: contents: write` \[39\]. |
| GCC Compile Farm account | Optional | Request at portal.cfarm.net; open-source use only, admin approval required \[31\]. |
| Zenodo archive and DOI | Optional | Configured in the Zenodo web UI, nothing in the repo \[K\]. |

## 9. Functions Definition

### C: `src/`

| File | Function | Signature | Responsibility |
| --- | --- | --- | --- |
| `main.c` | `main` | `int main(int argc, char **argv)` | Parse arguments, build schedule, run cells, write CSV, return exit code. |
| `main.c` | `parse_args` | `int parse_args(int, char **, config_t *)` | Validate modes, strides (multiples of 8), threads, blocks, seed. |
| `main.c` | `make_schedule` | `void make_schedule(cell_t *cells, size_t n, unsigned seed, int blocks)` | Seeded Fisher-Yates shuffle per block; insert sentinel; mark block 0 as warm-up. |
| `main.c` | `emit_row` | `void emit_row(FILE *, const cell_t *, const result_t *)` | Write one `raw.csv` row. |
| `topo.c` | `topo_load` | `int topo_load(topo_t *)` | Read `/sys/devices/system/cpu/cpu*/topology/core_cpus_list` (fall back to `thread_siblings_list`) and package id; read P-core and E-core lists where present. |
| `topo.c` | `topo_pick` | `int topo_pick(const topo_t *, placement_t, int threads, int *cpus_out)` | Choose CPUs for `cores` or `smt`; pair members on distinct cores. |
| `topo.c` | `pin_to_cpu` | `int pin_to_cpu(int cpu)` | `sched_setaffinity` on the calling thread \[41\]. |
| `alloc.c` | `alloc_counters` | `void *alloc_counters(size_t stride, int slots)` | `posix_memalign(4096)`, size rounded up to 4096, zeroed \[40\]. |
| `alloc.c` | `check_stride` | `int check_stride(size_t stride)` | Reject non-multiples of 8; warn at 4096 or above. |
| `kernel.c` | `run_cell` | `result_t run_cell(mode_t, size_t stride, int threads, const int *cpus, double target_s)` | One cell per FR-07: barrier, timed loop in 1,024-op chunks with shared stop flag, per-thread op counts written once to 256 B-spaced slots. |
| `kernel.c` | `print_layout` | `void print_layout(const void *base, size_t stride, int slots)` | Print slot addresses with 64 B line and 128 B chunk indices. |
| `meta.c` (optional) | `detect_line_size` | `size_t detect_line_size(void)` | sysfs `coherency_line_size`, then `sysconf(_SC_LEVEL1_DCACHE_LINESIZE)`, else 64; reported only, never used to change the sweep. |

### Python: `analysis/fs_stride_analysis/`

| Module | Function | Signature | Responsibility |
| --- | --- | --- | --- |
| `io.py` | `load_raw` | `(path) -> list[dict]` | Read CSV with `csv`; validate schema; raise `ValueError` naming a missing column. |
| `io.py` | `load_meta` | `(path) -> dict` | Validate against `schemas/meta.schema.json`. |
| `stats.py` | `log_ratios` | `(rows, config) -> dict[int, np.ndarray]` | Per stride, `ln(y(s,b)/y(256,b))` over blocks; also sentinel. |
| `stats.py` | `paired_t` | `(d: np.ndarray) -> (mean, sd, t, p_one_sided)` | One-sided paired t with `scipy.stats.t.sf` \[36\]. |
| `stats.py` | `holm` | `(pvals: list[float]) -> list[float]` | Holm adjusted p-values. |
| `stats.py` | `mde90` | `(sd: float, B: int, m: int, alpha: float) -> float` | `(t(B-1,1-alpha/m)+t(B-1,0.90))*sd/sqrt(B)`. |
| `classify.py` | `knee` | `(contended: dict[int,bool]) -> (int or None, str)` | Smallest stride with no larger stride contended; class or irregular. |
| `classify.py` | `classify_config` | `(summary, gate_pct) -> str` | Apply noise gate and class rules. |
| `sim.py` | `simulate_sweep` | `(sigma, rho, effect, B, seed) -> dict` | Synthetic sweep with log-normal noise, optional spikes and injected slowdown. |
| `sim.py` | `run_st01_st03` | `() -> bool` | Section 6 pass criteria. |
| `folklore.py` | `load_folklore` | `(path) -> dict` | Read `data/folklore.toml` with `tomllib`. |
| `folklore.py` | `compare` | `(summary, folklore, arch) -> list[dict]` | Join measured knee to assumed constants. |
| `report.py` | `make_figures` | `(summary, outdir) -> None` | Write PNGs. |
| `report.py` | `write_report` | `(summary, meta, outdir) -> None` | Write `report.md`, `summary.json`, `summary.csv`; fail if interval or gate is missing. |
| `cli.py` | `main` | `() -> int` | Entry point; exit codes 0, 1, 2, 4. |

### Shell

| Script | Responsibility |
| --- | --- |
| `scripts/run_all.sh` | Build, sweep, analyze, report; refuses to overwrite. |
| `scripts/capture_meta.sh` | Collect `lscpu`, kernel, governor, SMT, P/E lists, hypervisor flag, load average into `meta.json`. |
| `scripts/c2c_check.sh` | Optional `perf c2c` oracle \[3\]. |
| `scripts/msr_ablate.sh` | Optional Intel MSR 0x1A4 bit 1 toggle \[42\]; dry-run by default; restores on exit. |
| `scripts/resolve_pins.sh` | Look up latest releases at least 14 days old; update lock file and action SHAs. |
| `scripts/license_check.sh` | Query the GitHub license endpoint for each repository listed in `docs/related-work.md`. |

## 10. Project Tree

```
fs-stride/
  LICENSE  NOTICE  README.md  CITATION.cff  CHANGELOG.md  CONTRIBUTING.md  AGENTS.md  Makefile
  src/        main.c  topo.c  alloc.c  kernel.c  fs_stride.h
  analysis/
    pyproject.toml  requirements.lock
    fs_stride_analysis/  io.py  stats.py  classify.py  sim.py  folklore.py  report.py  cli.py
  schemas/    meta.schema.json  summary.schema.json  raw.schema.json
  scripts/    run_all.sh  capture_meta.sh  c2c_check.sh  msr_ablate.sh  resolve_pins.sh  license_check.sh
  tests/
    unit/         test_layout.c  test_alloc.c  test_topo.sh  test_asm.sh  test_schedule.sh  test_stats.py  test_classify.py  test_folklore.py
    integration/  smoke.sh  repro.sh  oracle.sh  msr_dryrun.sh
    fixtures/     sysfs_smt_on/  sysfs_smt_off/  sysfs_hybrid/  sysfs_dual_socket/  synthetic/
  data/       folklore.toml  ARCH-CPU-UTC/  (one directory per submitted machine)
  results/    (generated, git-ignored except .gitkeep)
  docs/       method.md  limitations.md  related-work.md  atlas.md  AUTHORSHIP.md
  paper/      main.tex  refs.bib
  .github/
    workflows/  ci.yml  measure.yml  release.yml  validate-data.yml
    dependabot.yml  PULL_REQUEST_TEMPLATE.md
    ISSUE_TEMPLATE/  bug.md  new-machine-result.md
```

## 11. Git Commit and PR Standards

- **Commit format:** Conventional Commits 1.0.0 \[33\]: `type(scope): summary`, summary at most 72 characters, imperative, no trailing period. Types: `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `ci`, `build`, `chore`, `data`. Scopes: `bench`, `analysis`, `scripts`, `ci`, `docs`, `data`. Breaking changes use `!` and a `BREAKING CHANGE:` footer. Examples: `feat(bench): add pair mode`; `fix(analysis): use paired t on log ratios`; `data: add i7 laptop run 2026-12-01`.
- **Sign-off:** `git commit -s` for the Developer Certificate of Origin \[34\]; CI rejects unsigned commits.
- **AI assistance:** commits that contain AI-written code carry an `Assisted-by:` trailer; `docs/AUTHORSHIP.md` lists which results you personally ran and checked.
- **Hooks:** pre-commit runs ruff, shellcheck, clang-format and a commit-msg check for the convention.
- **Branches:** `feat/<slug>`, `fix/<slug>`, `data/<machine>`, `docs/<slug>`, `ci/<slug>`. `main` is protected, no force-push, squash-and-merge; the PR title becomes the commit subject.
- **PR template:** What changed, Why, How tested, Reproduction command, Machine used (for timing changes).
- **PR rules:** at most 400 changed lines excluding data and generated files; one reviewer for code, two for `stats.py`, `sim.py`, `classify.py`; any change to those three must include the `make test-sim` output; data PRs must include `meta.json`, raw CSV and the sentinel results, and are rejected without them; CI green.
- **Versioning:** Semantic Versioning \[35\]; changelog in Keep a Changelog style \[43\].

## 12. CI/CD Pipeline Standards and Deployment Platform

**Platform:** GitHub Actions on GitHub-hosted runners, free for public repositories \[24\]. **Deployment target:** GitHub Releases \[39\]. This is a CLI plus data, so no container registry or cloud function.

**Runner matrix (explicit labels, never `ubuntu-latest`):** `ubuntu-24.04`, `ubuntu-26.04`, `ubuntu-24.04-arm`, `ubuntu-26.04-arm` \[24\]\[25\]. Compilers: GCC 14 and 16; Clang 22, and 23 where installable.

| Workflow | Trigger | Steps |
| --- | --- | --- |
| `ci.yml` | push, pull\_request | Permissions `contents: read`; build with `-Werror` on GCC and Clang; ruff, shellcheck, clang-format check; `cloc` line budget; unit tests under ASan and UBSan; `make test-asm`; `make test-sim`; DCO and Conventional Commits check; `make smoke`; schema validation; upload smoke report. |
| `measure.yml` | manual and weekly | Run `make sweep` on each runner type; upload raw data and `meta.json`. Not a gate: it feeds H3 and records hypervisor, CPU model and load average. |
| `validate-data.yml` | pull\_request touching `data/` | Schema check, meta completeness, sentinel present, regenerate `docs/atlas.md`. |
| `release.yml` | tag `v*` | Build tarball (source, analysis package, docs, no `results/`), compute `SHA256SUMS`, create the release with `GITHUB_TOKEN` and `contents: write`. |

**Quality gates (the build fails):** any unit or negative test; compiler warnings; `cloc` over budget; schema failure; ST-01 or ST-02 failing; unsigned commit; report without a Limitations section.

**Why measurement is not a gate:** shared-runner timing is noisy by construction, so a timing threshold in CI would be flaky. Gate only on code and statistics correctness.

**Supply chain:** every third-party action pinned to a full commit SHA with a version comment, using Node 24 based releases \[23\]; Dependabot for `github-actions` and `pip` \[38\]; `resolve_pins.sh` weekly.

**Release artifacts:** `fs-stride-vX.Y.Z.tar.gz`, `SHA256SUMS`, and one data bundle per machine. Install: `tar xzf fs-stride-*.tar.gz && make all`. Optional archive with a DOI through Zenodo \[K\].

## 13. Existing GitHub Projects and What to Use

I found no repository that does a cross-machine stride-sweep study with a noise floor and paired statistics \[U\]. Nearest neighbors:

| Project | What it is | Use in fs-stride | Limits |
| --- | --- | --- | --- |
| khale/false-sharing \[27\] | C microbenchmark where threads write distinct bytes inside one cache line; README validates with `perf c2c`. | Design reference and the `perf c2c` validation recipe for FR-17. | One layout, no sweep. License not confirmed: reimplement, do not copy. |
| joemario/perf-c2c-usage-files \[28\] | `false_sharing_example.c` with a `-DNO_FALSE_SHARING` switch and timestamp code for x86 and AArch64; sample reports. | Oracle workflow for IT-06 and the build-flag convention. | Demonstration only. License not confirmed. |
| perfgo examples/false-sharing \[29\] | Go benchmark pair, padded vs unpadded, with `perf c2c` steps. | Cross-language sanity check; related-work citation for the padded-vs-unpadded practice. | Not a sweep. |
| crossbeam-utils CachePadded \[2\] | Per-architecture padding table with reasoning. | Source of the assumed constants in `folklore.toml`. | A guess by its own docs; values vary by version, so freeze a version. |
| Linux perf c2c \[3\]\[4\] | HITM-based contention analysis with a double-cacheline option. | The independent oracle. | Needs PMU support: Intel, AMD IBS (not Zen 3), Arm SPE \[3\]. |
| plasma-umass (Sheriff, Stabilizer) \[30\] | Sheriff false-sharing detector and Stabilizer layout randomization. | Related work; Stabilizer idea for the layout-confound discussion. | Build status and license unverified. |
| actions/runner-images \[26\] | Defines the hosted runner environments. | Cite exact image versions for CI data. | n/a |
| GCC Compile Farm \[31\] | Shared SSH access to many architectures for open-source projects. | Stretch: extra architectures with sweeps under 3 minutes. | Approval needed, not a free compute cluster, shared machines: record load, label shared-host. |

Predator \[11\] and Huron \[13\] have papers but I could not confirm public repositories. Never copy code from any of these; run `scripts/license_check.sh` first if you ever plan to.

## 14. Build Backlog (run in order)

| ID | Deliverable | Verified by |
| --- | --- | --- |
| T00 | Repo bootstrap: LICENSE, AGENTS.md, Makefile, hooks, `.gitignore` | `make lint` |
| T01 | `topo.c` plus sysfs fixtures | UT-01 |
| T02 | `alloc.c` | UT-02 under sanitizers |
| T03 | `kernel.c` | UT-03, UT-04, UT-14 |
| T04 | `main.c`: CLI, schedule, CSV | UT-05, UT-06, NT-04 to NT-08 |
| T05 | `capture_meta.sh` and schemas | UT-12 |
| T06 | `io.py` | NT-01, NT-02 |
| T07 | `stats.py` | UT-07 to UT-09 |
| T08 | `sim.py` | ST-01 to ST-03 |
| T09 | `classify.py` | UT-10 |
| T10 | `folklore.toml` and `folklore.py` (only sources actually read) | UT-11 |
| T11 | `report.py` | UT-13, IT-01 |
| T12 | `run_all.sh`, `make smoke`, `make sweep` | IT-01 |
| T13 | Pilot on your machine, commit raw data | Gates G0, G1 |
| T14 | `c2c_check.sh` | IT-06 |
| T15 | `msr_ablate.sh` | IT-07 |
| T16 | `ci.yml`, `measure.yml`, `release.yml`, `validate-data.yml` | Green run on a test branch |
| T17 | `resolve_pins.sh`, `dependabot.yml` | Dry run prints a diff |
| T18 | `license_check.sh` | Prints a license or 'none' per repository |
| T19 | `atlas.md` generator | Golden test |
| T20 | Paper skeleton and `AUTHORSHIP.md` | `make paper` builds |

## 15. Gates and Pilot

| Gate | When | Pass criteria | If it fails |
| --- | --- | --- | --- |
| G0 kernel sanity | after T04 | On the dev machine, `atomic` at 2 threads on separate cores is at least 1.5x slower at stride 8 than at 256, and `sched_getcpu` matches the intended CPUs. | Debug pinning, SMT, VM; do not continue. |
| G1 noise | T13 | Sentinel MDE90 at most 10% for at least 80% of primary configurations. | Pivot the paper to the noise-envelope result (H3). |
| G2 controls | T13 | `volatile` and `pair` results recorded either way. | Report as found. |
| G3 coverage | before drafting claims | Raw data from at least 3 machines. | State limited coverage in the abstract. |

## 16. Known Unknowns

- Whether `pair` mode shows a 64 B vs 128 B difference on Intel at all; only data settles it.
- Whether `volatile` masking reproduces on bare metal.
- Exact current versions of LLVM 23.1.x, SciPy, Matplotlib, pytest, ruff, and the setup-python major.
- Folly's AArch64 constant, and every ecosystem constant not read directly; T10 must read each source at a pinned commit.
- Public repositories for Predator and Huron, and every license.
- Whether anyone has published a systematic cross-machine padding study; do a real literature search before claiming novelty.
- CPython issue 159860 mentioned in your audit was not verified; cite gh-144438 \[9\] instead.

## 17. References

1. Jayasena et al., Detection of False Sharing Using Machine Learning, SC'13. https://commit.csail.mit.edu/papers/2013/falsesharing-sc13.pdf \[V\]
2. crossbeam-utils `CachePadded` source. https://docs.rs/crossbeam-utils/latest/src/crossbeam\_utils/cache\_padded.rs.html \[V\]
3. perf-c2c(1). https://man7.org/linux/man-pages/man1/perf-c2c.1.html \[V\]
4. Linux perf c2c double-cacheline option (Feng Tang, Feb 2023). https://lore.kernel.org/r/20230214075823.246414-1-feng.tang@intel.com \[V via mirror\]
5. JVM `@Contended` padding. https://dzone.com/articles/what-false-sharing-is-and-how-jvm-prevents-it \[V\]
6. cppreference, hardware\_destructive\_interference\_size. https://en.cppreference.com/w/cpp/thread/hardware\_destructive\_interference\_size \[V\]
7. Stack Overflow 72126606 (mirror). https://kiwix.lema.org/stackoverflow.com\_en\_all\_2023-11/questions/72126606/should-the-cache-padding-size-of-x86-64-be-128-bytes \[V\]
8. Mechanical Sympathy, Prefetching and false sharing. https://groups.google.com/g/mechanical-sympathy/c/i3-M2uCYTJE \[V\]
9. CPython gh-144438 patch. https://github.com/python/cpython/pull/144554.patch \[V\]
10. Liu and Berger, SHERIFF, OOPSLA 2011. https://people.cs.umass.edu/\~emery/pubs/res005-liu.pdf \[V\]
11. Liu et al., PREDATOR, PPoPP 2014. https://people.cs.umass.edu/\~emery/pubs/Predator-ppopp14.pdf \[V\]
12. Liu and Liu, Cheetah, CGO 2016. https://core.ac.uk/download/235418437.pdf \[V\]
13. Khan et al., Huron, PLDI 2019. https://homes.cs.washington.edu/\~baris/public/huron.pdf \[V\]
14. GCC 16 and GCC 14 release pages. https://gcc.gnu.org/gcc-16/ and https://gcc.gnu.org/gcc-14/ \[V\]
15. GCC 16.2 coverage. https://phoronix.com/news/GCC-16.2-Released \[V\]
16. LLVM site and schedule; LLVM 22 coverage. https://llvm.org/ and https://phoronix.com/news/llvm-clang-22.1-released \[V\]
17. Python 3.15.0 and downloads. https://www.python.org/downloads/release/python-3150/ and https://blog.python.org/2026/10/python-3150-final-is-here/ and https://www.python.org/downloads/ \[V\]
18. NumPy releases. https://github.com/numpy/numpy/releases and https://numpy.org/news/ \[V\]
19. SciPy 1.18 release month, via JAX support policy. https://docs.jax.dev/en/latest/deprecation.html \[V\]
20. Matplotlib 3.10.9 seen in a Dependabot PR. https://github.com/Unidata/MetPy/pull/4045 \[V\]
21. actions/checkout releases. https://github.com/actions/checkout/releases \[V\]
22. actions/upload-artifact and setup-python releases. https://github.com/actions/upload-artifact/releases , https://github.com/actions/setup-python/releases ; pin-list evidence https://docs.rs/crate/release-kit/0.8.3/source/versions.toml \[V, weak\]
23. Node 20 removal. https://github.blog/changelog/2026-09-24-node-20-is-no-longer-available-in-github-actions/ \[V\]
24. GitHub-hosted runners. https://docs.github.com/en/actions/reference/runners/github-hosted-runners \[V\]
25. Ubuntu 26 GA and latest migration. https://github.blog/changelog/2026-09-17-ubuntu-26-generally-available-and-latest-migration \[V\]
26. actions/runner-images releases. https://github.com/actions/runner-images/releases \[V\]
27. khale/false-sharing. https://github.com/khale/false-sharing \[V\]
28. joemario/perf-c2c-usage-files. https://github.com/joemario/perf-c2c-usage-files \[V\]
29. perfgo false-sharing example. https://pkg.go.dev/github.com/perfgo/perfgo/examples/false-sharing \[V\]
30. PLASMA group software (Sheriff, Stabilizer). https://people.cs.umass.edu/\~emery/plasma/emery/plasma.html \[V\]
31. GCC Compile Farm. https://gcc.gnu.org/wiki/CompileFarm and https://portal.cfarm.net/users/new/ \[V\]
32. OpenMP specifications. https://www.openmp.org/specifications/ \[K\]
33. Conventional Commits 1.0.0. https://www.conventionalcommits.org/en/v1.0.0/ \[K\]
34. Developer Certificate of Origin. https://developercertificate.org/ \[K\]
35. Semantic Versioning. https://semver.org/ \[K\]
36. SciPy statistics reference (`ttest_rel`, `t`). https://docs.scipy.org/doc/scipy/reference/stats.html \[K\]
37. Benchmarking methodology to read and cite (look up exact records): Georges, Buytaert, Eeckhout, Statistically Rigorous Java Performance Evaluation, OOPSLA 2007; Mytkowicz et al., Producing Wrong Data Without Doing Anything Obviously Wrong, ASPLOS 2009; Kalibera and Jones, Rigorous Benchmarking in Reasonable Time, ISMM 2013 \[K\]
38. Dependabot documentation. https://docs.github.com/en/code-security/dependabot \[K\]
39. GitHub token and releases documentation. https://docs.github.com/en/actions/security-for-github-actions/security-guides/automatic-token-authentication and https://docs.github.com/en/repositories/releasing-projects-on-github \[K\]
40. posix\_memalign(3). https://man7.org/linux/man-pages/man3/posix\_memalign.3.html \[K\]
41. sched\_setaffinity(2). https://man7.org/linux/man-pages/man2/sched\_setaffinity.2.html \[K\]
42. Intel Software Developer Manuals (MSR 0x1A4 prefetcher control). https://www.intel.com/content/www/us/en/developer/articles/technical/intel-sdm.html \[K\]
43. Keep a Changelog. https://keepachangelog.com/ \[K\]
