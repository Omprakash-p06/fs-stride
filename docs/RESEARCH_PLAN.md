> **Canonical hierarchy:** `AGENTS.md` > `RESEARCH_PLAN.md` > `Spec v2.0.md` > `README.md` for design decisions; `Spec v2.0.md` > `RESEARCH_PLAN.md` > `AGENTS.md` > `README.md` for interface contracts (FRs, NFRs, test IDs, schemas, CLI flags). Conflicts are resolved in [decisions.md](decisions.md).

# Technical Audit, Quantitative Redesign, and Implementation Blueprint for fs-stride

The `fs-stride` specification targets an unresolved, practically consequential systems problem: major runtimes and standard libraries still disagree by 2× to 4× on cache-line padding distances, and real production scaling regressions continue to appear—including CPython `gh-144438` (Feb 2026) and CPython Issue `#159860` (Oct 2026, free-threaded builds of CPython 3.13–3.15), where 64 B QSBR thread-state padding limited 14-core CPU-bound thread scaling on an Apple M4 Pro to roughly 6× (and 2.3–4× across most of `Tools/ftscalingbench`) versus ~10× for separate processes before switching to 128 B.

However, an end-to-end microarchitectural, resource, and statistical audit of Draft 1.0 uncovers five structural defects that prevent the plan from validating its own hypotheses and acceptance criteria:

1. A `volatile` increment kernel masked by store-buffer forwarding on tested Intel hardware.
2. A tight single-counter loop that generates no ongoing L2 misses and therefore leaves H1 unfalsifiable.
3. Raw `aligned_alloc(4096, size)` calls that violate strict C11 size-multiple rules on 91.4–100% of default 4-core to 16-core test cells (failing under strict allocators such as LLVM Scudo).
4. Fixed-iteration doubling calibration that breaches the 15-minute NFR-01 wall-clock limit (reaching 16.5–19.4 minutes on 4 cores and 30.2–66.7 minutes on 16 cores).
5. An FR-11/FR-12/ST-01 statistical pipeline handicapped by a 20.04× variance-scaling mismatch, a unit inconsistency, a 31.06% spurious ST-01 failure rate on pure noise, and a premature 2.90% per-trial noise cliff.

The redesign replaces these brittle components with three simpler mechanisms:

1. **Multi-mode C11 kernel:** `atomic` (`atomic_fetch_add_explicit(..., memory_order_relaxed)`) measures hardware coherency granularity (H2); `coupled-pair`—a single-page (4 KB) ping-pong kernel—forces continuous L2 Read-For-Ownership (RFO) misses to test Intel's L2 adjacent-line prefetcher (H1); `volatile` serves as the store-buffer control (H4); and `rw-asymmetric` captures asymmetric reader/writer contention.
2. **50 ms per-cell time-capped chunked execution:** Replaces global doubling calibration, reporting `ns_per_op = elapsed_s * 1e9 * threads / total_ops` (where `total_ops` is the sum across all threads) with `K = 65,536` ops per chunk, keeping sweeps within NFR-01's runtime budget.
3. **Within-block paired log-ratio inference with Holm-Bonferroni FWER control (1%) and an MDE90 gate:** Replaces the separate 200-pair A/A percentile rule and jackknife-fragile BCa median bootstrap, lowering `MDE90` sensitivity to 1.66–2.36% at 2% trial noise, removing the 400-cell-per-thread A/A runtime tax, and cutting Python analysis time ~29.5× (to 0.062 s and 0.02 MB RAM).

In Phase 2 (after Gate G1 passes), the tool pairs with two optional extensions: a privileged causal MSR prefetcher ablation script (`scripts/msr_ablate.sh`) toggling Intel `MSR_MISC_FEATURE_CONTROL` (`0x1A4` bit 1) and AMD Zen 4/5 `PrefetchControl` (`0xC0000108`) on bare metal, and cross-ISA execution across the GCC Compile Farm (`portal.cfarm.net`) to compare measured knees against the 7-ecosystem padding folklore (`crossbeam`, `Folly`, `HotSpot`, `Go`, `Linux`, `C++17`, `CPython`).

---

## Microarchitectural Audit: Four Defects in the Draft Kernel

### Defect 1: Store-Buffer Forwarding Masks False Sharing in `volatile` Loops

Draft 1.0 specifies a C kernel (`run_cell`) in which each thread performs `iters` increments on its own `volatile uint64_t` counter at byte offset `i * stride`. While `volatile` stops the compiler from hoisting the counter into a register (passing disassembly checks for a load-add-store loop), out-of-order execution pipelines can mask false sharing in hardware. Measurements from an independent engineering benchmark note (`notes.elimelt.com`, `[U]`) on a 4-vCPU Intel Xeon Emerald Rapids KVM guest (GCC 13.3.0 `-O2`, threads pinned with `pthread_setaffinity_np`) showed that a `volatile` increment loop exhibited no statistically measurable false-sharing penalty between 8 B and 256 B stride: 4-thread medians remained flat at 0.46 ns/increment at 8 B, 0.46 ns at 64 B, and 0.34 ns at 256 B, all within run-to-run variation (0.30–2.13 ns).

The benchmark author attributes this masking—while explicitly noting it was not verified with hardware performance counters on that host—to intra-core store-to-load forwarding and batched store-buffer retirement. Because each thread reads and writes only its own slot, each load can forward directly from the prior store sitting in the core's private store buffer without stalling for L1D ownership; whenever the core briefly acquires the line in Modified/Exclusive state, it drains a batch of buffered stores in one ownership window, amortizing a measured 91–119 ns inter-core coherence handoff across many increments. Replacing the `volatile` increment with C11 `atomic_fetch_add_explicit(&counter, 1, memory_order_relaxed)` forces a serializing read-modify-write (`lock addq` on x86-64; LSE `ldadd` or LL/SC `ldxr/stxr` on AArch64) that cannot bypass cache coherence. On that same Emerald Rapids host, relaxed atomics exposed an 8.5× slowdown with 2 threads (49.8 ns at 8 B vs 5.9 ns at 64 B) and a 21.7× slowdown with 4 threads (135.7 ns at 8 B vs 6.3 ns at 64 B).

| Access Pattern (Emerald Rapids KVM, `notes.elimelt.com` `[U]`) | Stride 8 B | Stride 16 B | Stride 32 B | Stride 64 B | Stride 128 B | Stride 256 B | Penalty Ratio (8 B / 64 B) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `atomic_fetch_add` (relaxed, 2 threads) | 49.8 ns | 49.4 ns | 44.2 ns | 5.9 ns | 5.8 ns | 6.1 ns | 8.44× (8.5× reported) |
| `atomic_fetch_add` (relaxed, 4 threads) | 135.7 ns | 129.8 ns | 57.3 ns | 6.3 ns | 6.0 ns | 6.6 ns | 21.54× (21.7× reported) |
| `volatile` load-add-store (2 threads) | 0.30 ns | 0.33 ns | 0.32 ns | 0.34 ns | 0.27 ns | 0.26 ns | 0.88× (flat within noise) |
| `volatile` load-add-store (4 threads) | 0.46 ns | 0.42 ns | 0.44 ns | 0.46 ns | 0.29 ns | 0.34 ns | 1.00× (flat within noise) |
| Plain `(*c)++` at `-O2` (4 threads) | <0.001 ns | <0.001 ns | <0.001 ns | <0.001 ns | <0.001 ns | <0.001 ns | Hoisted into register |
| Asymmetric Reader next to `volatile` Writer (4 threads) | 0.72 ns/load | — | — | 0.31 ns/load | — | — | 2.32× reader (1.63× writer) |

*Data source: Independent blog microbenchmark (`notes.elimelt.com` `[U]`, 20M atomic / 200M volatile ops per thread, Intel Xeon Emerald Rapids 4-vCPU KVM guest, GCC 13.3.0).*

Switching to C11 atomics introduces two cross-architecture details. On AArch64, compilers targeting baseline ARMv8.0 emit Load-Linked/Store-Conditional (`ldxr/stxr`) retry loops (or outline atomic helper calls unless `-mno-outline-atomics` is used) whose contention behavior differs sharply from ARMv8.1+ Large System Extensions (LSE) single-instruction `ldadd`. Consequently, `meta.json` records both `-march`/`-moutline-atomics` flags and the actual disassembled atomic opcode verified by `UT-04`. Retaining the asymmetric reader-writer pattern (`--mode rw-asymmetric`) captures non-atomic workloads in which a single `volatile` writer slows adjacent readers by 2.3×–2.4×.

### Defect 2: Tight Per-Thread Loops Cannot Falsify H1 (L2 Spatial Prefetcher)

Even after upgrading `run_cell` to relaxed atomics, a single-counter-per-thread tight loop cannot falsify H1 on Intel x86-64. As Intel's Optimization Reference Manual and microarchitectural analyses (including Peter Cordes's Stack Overflow `#72126606` explanation) describe, Intel's L2 Adjacent Cache Line (Spatial) Prefetcher—present since the Sandy Bridge family and controlled by MSR `0x1A4` bit 1—only activates when a cache miss reaches the L2 cache and spare off-core request-tracking bandwidth exists, attempting to pull in the partner 64 B line that completes a 128 B aligned pair. In a tight per-thread loop at stride 64 B, each core acquires Exclusive/Modified ownership of its distinct 64 B line during initial iterations and retains it in private L1D thereafter—generating zero ongoing L1D misses and zero L2 requests. As a result, neither QuarticCat's original tight-loop microbenchmark on an Intel i7-6700K (Stack Overflow `#72126606`, where 64 B vs 128 B showed identical ~0.14 s runtime and differed only by ~500 vs ~22 transient startup `machine_clears.memory_ordering` events) nor the Emerald Rapids atomic sweep above (6.3 ns at 64 B vs 6.0 ns at 128 B) detected a 128 B knee.

#### Calculation 1: L2-Eviction Working-Set Sizing (Why Streaming Ring Buffers Fail)

An intuitive workaround is to sweep each thread across a multi-slot ring buffer large enough to evict its private L2 cache. Quantifying the exact memory footprint exposes why this approach is brittle across modern CPUs. To reliably evict a private L2 cache of size $C_{\text{L2}}$ under pseudo-LRU or DRRIP replacement policies, each thread must touch an over-subscription factor $\alpha \in \{2, 4\}$ of distinct 64 B cache lines, while separating consecutive slots by a pitch $P_{\text{slot}} \ge \text{next\_pow2}(T \cdot s_{\max})$ so Thread $T-1$ in slot $k$ never collides with Thread 0 in slot $k+1$:

$$N_{\text{lines/thread}} = \frac{\alpha \cdot C_{\text{L2}}}{64\text{ B}}, \qquad \text{Buffer Size} = N_{\text{lines/thread}} \times P_{\text{slot}}$$

For 4 threads at maximum stride 512 B, $P_{\text{slot}} = 2{,}048\text{ B}$. Plugging documented Arm/AMD/Apple L2 capacities alongside representative x86 L2 models into this formula exposes an L2-vs-L3 trap:

| Microarchitecture / Cache Model | L2 / Shared L3 (SLC) | Distinct 64 B Lines/Thread (2× L2) | Distinct 64 B Lines/Thread (4× L2) | Total Buffer at 2,048 B Pitch (4× L2) | Streaming Feasibility |
| :--- | :---: | :---: | :---: | :---: | :--- |
| Small-L2 x86 model (e.g., Skylake client) | 0.25 MB / 12 MB | 8,192 | 16,384 | 32 MB (>2.6× L3) | Spills to DRAM |
| Mid-L2 x86 model (e.g., Zen 3) | 0.50 MB / 32 MB | 16,384 | 32,768 | 64 MB (2.0× L3) | Spills to DRAM |
| AMD Zen 4 (verified 1 MB L2) / model L3 | 1.00 MB / 32 MB | 32,768 | 65,536 | 128 MB (4.0× L3) | Spills to DRAM |
| ARM Neoverse N1 (Graviton2 / Altra, verified) | 1.00 MB / 32 MB | 32,768 | 65,536 | 128 MB (4.0× L3) | Spills to DRAM |
| ARM Neoverse V2 (Graviton4, verified) | 2.00 MB / 36 MB | 65,536 | 131,072 | 256 MB (>7.1× L3) | Spills to DRAM |
| Large-L2 x86 model (e.g., Golden Cove / Rapids) | 2.00 MB / 30–105 MB | 65,536 | 131,072 | 256 MB (2.4–8.5× L3) | Spills to DRAM |
| Apple M1 Firestorm cluster (verified) | 12.0 MB shared / 8 MB SLC | 393,216 (196,608 at 128 B) | 786,432 (393,216 at 128 B) | 1,536 MB (768 MB at 128 B) | Spills to DRAM |

If a streaming benchmark picks a fixed 8 MB buffer with a 2,048 B slot pitch, each thread touches only 4,096 distinct lines (256 KB)—fitting inside a 1–2 MB L2 with zero L2 misses; conversely, scaling to 4× L2 forces 32–256 MB buffers that overflow L3 into DRAM (~80–100 ns latency), swamping L2 prefetcher behavior.

#### Resolution for H1: The 4 KB Coupled-Pair Ping-Pong Kernel (`coupled-pair`)

Following Peter Cordes's design (Stack Overflow `#72126606`)—under which QuarticCat's follow-up comment reported a clear 64 B vs 128 B performance difference on Intel but not on AMD Ryzen 3700X (though another contributor noted that spatial-prefetcher ping-ponging varies across Intel microarchitectures and scheduler placements)—group an even number of threads ($T \in \{4, 8, \dots, P\}$) into contending pairs on distinct physical cores: Pair 0 (Threads 0 and 1) runs `atomic_fetch_add` on byte offset `0`, while Pair 1 (Threads 2 and 3) runs `atomic_fetch_add` on byte offset `stride`, and generally Pair $k$ targets `k * stride`. Because the two cores inside each pair continuously bounce ownership of their shared counter, every handoff forces an L1+L2 RFO miss regardless of L2 size, inside a single 4,096 B page with zero cache-capacity tuning. At `stride = 64` B, offsets 0 and 64 sit inside one 128 B aligned pair, allowing Intel's L2 spatial prefetcher to fetch and downgrade the neighboring pair's Modified line and couple 2 independent pairs into a 4-thread contention ring; at `stride = 128` B, offset 64 is unowned and cold, decoupling the pairs.

Two hardware caveats must be captured in `meta.json` so H1 and H2 are never misread:

1. Intel's hardware prefetch tuning documentation states that the L2 Spatial Prefetcher is unavailable on Intel E-cores; on hybrid desktop/laptop CPUs, placing threads on E-cores instead of P-cores shifts H1 from `pair128` to `line64`, so `capture_meta.sh` logs `/sys/devices/cpu_core/cpus` and `/sys/devices/cpu_atom/cpus` and `topo_pick` defaults to P-cores only.
2. On Apple M1–M4 SoCs, physical L1D lines are 64 B—reported as 64 B by `CTR_EL0` and `getconf` under Asahi Linux—whereas L2 and System-Level Cache (SLC) lines (and macOS `sysctl hw.cachelinesize`) are 128 B. Running `fs_stride` on bare-metal Apple M1 Linux shows `detect_line_size()` returning 64 B while `atomic` mode measures a 128 B cross-core knee (consistent with CPython Issue `#159860`'s C microbenchmark showing 0.64–0.80 ns/iter at 64 B vs 0.33–0.38 ns/iter at 128 B on M4 Pro), demonstrating why OS-reported L1 line sizes cannot substitute for empirical measurement.

### Defect 3: Strict C11 `aligned_alloc(4096, size)` Violations and L1D Set Aliasing

#### Calculation 2: Exact Memory Geometry and Cache-Set Wrap Analysis

Draft 1.0 allocates counter buffers with raw `aligned_alloc(4096, size)`. Under strict ISO C11 (§7.22.3.1), passing a size that is not an exact integral multiple of alignment was undefined behavior. Although WG14 DR460/N2072, C17, C23, modern glibc (>= 2.38), musl, and jemalloc lifted that restriction, hardened allocators such as LLVM's Scudo still reject non-multiple sizes with `EINVAL` or abort (tracked in LLVM issue `#226030`, September 2026). Evaluating `raw_bytes = threads * stride` across all 7 default strides (8–512 B) confirms that raw sizes violate strict C11 on 21 of 21 cells (100.0%) on a 4-core host (`1, 2, 4`), 32 of 35 cells (91.4%) on a 16-core host (`1, 2, 4, 8, 16`), and 36 of 42 cells (85.7%) on a 32-core host (`1..32`).

| Stride (B) | Threads | Raw Span (B) | Page-Rounded Size (B) | Strict C11 Raw Valid? | Max Counters per 64 B Line | Max Counters per 128 B Pair | 4 KB Pages Touched | Max per 64-Set L1D Set | Max per 256-Set L1D Set |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 8 | 2 / 4 / 8 / 16 | 16 / 32 / 64 / 128 | 4,096 | No (all 4) | 2 / 4 / 8 / 8 | 2 / 4 / 8 / 16 | 1 | 2 / 4 / 8 / 8 | 2 / 4 / 8 / 8 |
| 16 | 2 / 4 / 8 / 16 | 32 / 64 / 128 / 256 | 4,096 | No (all 4) | 2 / 4 / 4 / 4 | 2 / 4 / 8 / 8 | 1 | 2 / 4 / 4 / 4 | 2 / 4 / 4 / 4 |
| 32 | 2 / 4 / 8 / 16 | 64 / 128 / 256 / 512 | 4,096 | No (all 4) | 2 / 2 / 2 / 2 | 2 / 4 / 4 / 4 | 1 | 2 / 2 / 2 / 2 | 2 / 2 / 2 / 2 |
| 64 | 2 / 4 / 8 / 16 | 128 / 256 / 512 / 1,024 | 4,096 | No (all 4) | 1 / 1 / 1 / 1 | 2 / 2 / 2 / 2 | 1 | 1 / 1 / 1 / 1 | 1 / 1 / 1 / 1 |
| 128 | 2 / 4 / 8 / 16 / 32 | 256–4,096 | 4,096 | Only at 32t | 1 (all) | 1 (all) | 1 | 1 (all) | 1 (all) |
| 256 | 2 / 4 / 8 / 16 / 32 | 512–8,192 | 4,096 (8,192 at 32t) | Only at 16t, 32t | 1 (all) | 1 (all) | 1 (2 at 32t) | 1 (2 at 32t) | 1 (all) |
| 512 | 2 / 4 / 8 / 16 / 32 | 1,024–16,384 | 4,096–16,384 | Only at 8t, 16t, 32t | 1 (all) | 1 (all) | 1 / 1 / 1 / 2 / 4 | 1 / 1 / 1 / 2 / 4 | 1 (all) |

*Calculation 2 source: Exact offset indexing $\lfloor i \cdot s / 64 \rfloor$, $\lfloor i \cdot s / 128 \rfloor$, and $(\lfloor i \cdot s / 64 \rfloor) \bmod N_{\text{sets}}$.*

Calculating the L1D set-index wrap period via $N_{\text{sets}} = C_{\text{L1D}} / (W \cdot L)$ and $\text{Wrap} = N_{\text{sets}} \cdot L$ also flags a subtle hardware confound for `smt-sibling` runs (where two hardware threads share one core's L1D). Both 32 KB 8-way (64 B line) and 48 KB 12-way (64 B line) x86 L1D caches contain exactly 64 sets, wrapping every 4,096 B (4 KB), whereas ARM Neoverse N1/V2 (verified 64 KB 4-way, 64 B line) and a 128 KB 8-way 64 B model (representing Apple P-core L1D, where associativity is unverified in public docs) contain 256 sets and wrap every 16,384 B (16 KB). At stride 512 B with 16–32 threads on 64-set x86 cores, threads $i$ and $i+8$ collide in the same L1D set (`threads * stride >= 4096`), and any user sweep requesting `--strides 4096` maps all threads to Set 0 and risks intra-core 4 KB load-store aliasing under SMT. Both issues are solved cleanly: `alloc_counters` uses `posix_memalign(&ptr, 4096, round_up_4096(raw_size))` followed by `memset` (and `atomic_init` for `_Atomic` counters), and `check_stride` emits a `meta.json` warning whenever `threads * stride >= 4096` (including `--strides 4096`).

### Defect 4: OpenMP `OMP_PROC_BIND` / `OMP_PLACES` Pinning Fragility

Implementing `--placement` (`cores`, `smt-sibling`, `spread`) through `OMP_PROC_BIND` and `OMP_PLACES` creates three practical failure modes across Linux runtimes (`libgomp` vs `libomp`). OpenMP parses `OMP_PLACES` statically at program startup, making multi-placement sweeps inside one binary awkward. Setting `OMP_PLACES` without `OMP_PROC_BIND` leaves affinity disabled in standard OpenMP, while binding the main thread under `libgomp` has caused thread-count pool regressions in production frameworks such as PyTorch (issue `#206479`). Worse, `OMP_PLACES=threads` with `OMP_PROC_BIND=close` only pins Threads 0 and 1 onto SMT siblings if Linux numbers sibling logical CPUs consecutively (`0,1, 2,3`), whereas many desktop and dual-socket kernels enumerate physical cores first (`0..P-1`) and SMT siblings second (`P..2P-1`), silently turning `smt-sibling` into cross-core placement.

The runtime-independent fix uses OpenMP solely for thread spawning and barriers (`#pragma omp parallel num_threads(t)`), while pinning each thread explicitly inside the parallel region via Linux `sched_setaffinity(0, sizeof(cpu_set_t), &mask)` driven by `topo.c` reading `/sys/devices/system/cpu/cpu*/topology/core_cpus_list` (falling back to `thread_siblings_list`), `physical_package_id`, and LLC `shared_cpu_list`. Placements map unambiguously: `cores` = one thread per physical core (intra-socket/LLC first); `smt-sibling` = two threads per physical core (exploratory-only); `spread` = one thread per socket/package (allowed on `cores`-equivalent primaries). Logging each thread's actual `sched_getcpu()` result into `raw.csv`'s `cpus` column guarantees identical behavior across GCC `libgomp` and Clang `libomp` and runs all placements inside a single process.

---

## Runtime and Resource Calculations: Fixing NFR-01 and NFR-02

### Calculation 3: Doubling-Calibration Overshoot and NFR-01 Wall-Clock Model

Draft 1.0 first contains an internal requirement contradiction: NFR-01 budgets 15 minutes for "7 strides, 5 thread counts, 2 placements, 30 trials, plus null... on a 4-core laptop (about 2,100 trials)", whereas FR-04 defaults thread counts to powers of two up to physical cores $P$ (`1, 2, 4, ..., P`) and rejects $>P$ without `--oversubscribe`. Consequently, a 4-core laptop ($P = 4$) runs 3 thread counts (`1, 2, 4`), while 5 thread counts (`1, 2, 4, 8, 16`) applies to a 16-core host.

More critically, Draft 1.0 calibrates a single global iteration count `iters` by doubling iterations until a stride-256, 2-thread cell exceeds $T_{\text{target}} = 100\text{ ms}$. Two hidden multipliers compound under this design. First, doubling from initial guess $N_0$ stops at $N = N_0 \cdot 2^k$ where $k = \lceil \log_2(T_{\text{target}} / (N_0 t_{\text{op}})) \rceil$, leaving $\log_2(T_0 / T_{\text{target}}) = U \sim \text{Uniform}(0, 1)$. Thus the calibrated baseline duration $T_0 = T_{\text{target}} \cdot 2^U$ lies on $[100, 200)\text{ ms}$ with exact mean and median:

$$E[T_0] = T_{\text{target}} \int_0^1 2^u\,du = \frac{100\text{ ms}}{\ln 2} = 144.27\text{ ms}, \qquad \text{Median}[T_0] = 100\sqrt{2} = 141.42\text{ ms}$$

Second, fixing `iters` to the uncontended baseline causes every contended cell (strides 8, 16, and 32 B for $t \ge 2$) to stretch by a contention slowdown multiplier $M(s, t) \gg 1$. Plugging the Emerald Rapids atomic slowdowns from `notes.elimelt.com` (`[U]`, relative to 6.1 ns at $t = 2$, stride 256 B: 8.16×, 8.10×, 7.25× at $t = 2$; and 22.25×, 21.28×, 9.39× at $t = 4$) into one 4-core block (21 cells across $t \in \{1, 2, 4\}$) sums to 91.38× $T_0$—an average of 4.35× $T_0$ per cell, not 1×. Summing calibration ($\approx 2 T_0$), 31 blocks across 2 placements, and 200 A/A pairs (400 cells) per thread count (or per thread-placement if $m_{\text{pl}} = 2$) gives exact wall time:

$$T_{\text{total}} = 2 T_0 + 2 \cdot 31 \cdot T_0 \sum_{t \in \mathcal{T}} \sum_{s \in \mathcal{S}} M(s, t) + 400 \cdot |\mathcal{T}| \cdot m_{\text{pl}} \cdot T_0$$

| Sweep Design & Contention Scenario | Baseline $T_0$ (ms) | Regular + Warm-up Cells | A/A Cells ($m_{\text{pl}}=1$ / $2$) | Regular Time (min) | Total Wall Time ($m_{\text{pl}}=1$ / $2$) | Meets NFR-01 ($\le 15$ min)? |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| Draft 1.0: 4-core (1,2,4), Ideal 1× naive | 100.0 | 1,302 | 1,200 / 2,400 | 2.17 | 4.17 / 6.17 min | Yes (unrealistic) |
| Draft 1.0: 4-core (1,2,4), Emerald Rapids atomics `[U]` | 100.0 | 1,302 | 1,200 / 2,400 | 9.44 | 11.44 / 13.44 min | Marginal (min $T_0$) |
| Draft 1.0: 4-core (1,2,4), Emerald Rapids atomics `[U]` | 144.3 | 1,302 | 1,200 / 2,400 | 13.62 | 16.51 / 19.39 min | No (Breaches NFR-01) |
| Draft 1.0: 4-core (1,2,4), Emerald Rapids atomics `[U]` | 190.0 | 1,302 | 1,200 / 2,400 | 17.94 | 21.74 / 25.54 min | No (Breaches NFR-01) |
| Draft 1.0: 16-core (1..16), Moderate contention | 144.3 | 2,170 | 2,000 / 4,000 | 25.36 | 30.17 / 34.98 min | No (2.0–2.3× over) |
| Draft 1.0: 16-core (1..16), 20× contended strides | 144.3 | 2,170 | 2,000 / 4,000 | 39.22 | 44.03 / 48.84 min | No (2.9–3.3× over) |
| Draft 1.0: 16-core (1..16), 30× multi-socket | 144.3 | 2,170 | 2,000 / 4,000 | 57.11 | 61.92 / 66.73 min | No (4.1–4.5× over) |
| **50 ms Cap: 4-core, 1 regime, $B = 30+1$** | 52.0 (cap) | 1,302 | 186 (1/block) | 1.13 | **1.29 min** | Yes (11.6× under) |
| **50 ms Cap: 4-core, Dual-Regime, $B = 30+1$, `cores`** | 52.0 (cap) | 651–868 | 93–124 (1/block) | 0.56–0.75 | **0.65–0.86 min** | Yes |
| **50 ms Cap: 16-core, 1 regime, $B = 30+1$** | 52.0 (cap) | 2,170 | 310 (1/block) | 1.88 | **2.15 min** | Yes (7.0× under) |
| **50 ms Cap: 16-core, Dual-Regime, $B = 30+1$, `cores` + `smt-sibling`** | 52.0 (cap) | 3,472–4,340 | 496–620 (1/block) | 3.01–3.76 | **3.44–4.30 min** | Yes (3.5× under) |

*Calculation 3 source: Exact summation over Draft 1.0 schedules, Emerald Rapids atomic multipliers (`[U]`), and 50 ms time-capped chunked loops (+2 ms barrier/chunk margin).*

Implementing per-cell time-capped chunked execution is simpler than Draft 1.0's calibration routine. Inside `run_cell`, all threads synchronize on an OpenMP barrier, record `t_start`, execute a fixed chunk of `K = 65,536` operations (taking ~0.4 ms uncontended atomic or ~8.9 ms under 22× contention), cross a barrier, and repeat until Thread 0 observes `elapsed >= 0.050 s`, then emit `total_ops` (summed across all `threads` threads), `elapsed_s`, and `ns_per_op = elapsed_s * 1e9 * threads / total_ops`. Every cell executes >330,000 contended (or >8 million uncontended) atomic operations, amortizing barrier and timer overhead. Under extreme 30× contention, the final 65,536-op chunk can push total cell duration above 59 ms (e.g., ~72 ms); therefore, `UT-14` allows `50–100 ms` on the dev machine and emits a warning only when `(last_chunk_duration / cell_duration) > 0.25`.

### Calculation 4: NFR-02 Analysis Speed, Memory Footprint, and BCa Degeneracy

To verify NFR-02 (`analyze` < 10 s on a default sweep using `scipy.stats.bootstrap(..., n_resamples=10000, method='BCa')` on median ratios), we benchmarked 60 non-reference cells (30 trials per cell) in Python with `tracemalloc` and ran synthetic edge-case checks.

| Estimator & Method (60 Cells, $n = 30$) | Wall Time (60 Cells) | Time / Cell | Peak Traced RAM | Raw Bootstrap Array Size | Edge-Case Behavior Observed |
| :--- | :---: | :---: | :---: | :---: | :--- |
| SciPy BCa median ratio (`batch=None`, 10k resamples) | 1.824 s | 30.4 ms | 7.50 MB | 4.80 MB ($2 \times 10^4 \times 30 \times 8$ B) | `NaN` CI + `DegenerateDataWarning` on zero-CV flat data; point collapse `(1.05, 1.05)` under 1 ms quantization |
| SciPy BCa median ratio (`batch=1000`, 10k resamples) | 2.033 s | 33.9 ms | 0.85 MB | 0.48 MB | Same jackknife degeneracy on ties or flat plateaus |
| SciPy Percentile median ratio (`batch=None`) | 1.616 s | 26.9 ms | 7.50 MB | 4.80 MB | Avoids jackknife `NaN`, still ~26× slower than paired t |
| SciPy BCa mean ratio (`batch=None`) | 0.991 s | 16.5 ms | 7.21 MB | 4.80 MB | Still yields `NaN` on zero-CV flat data |
| Vectorized NumPy percentile median (10k resamples) | 1.370 s | 22.8 ms | 9.97 MB | 4.80 MB | Clean optional non-parametric fallback |
| **Analytical Paired Log-Ratio t-Interval** | **0.0619 s** | **1.03 ms** | **0.02 MB** | **<0.01 MB** | **29.5× faster; avoids jackknife degeneracy (needs trivial zero-SD guard)** |

*Calculation 4 source: Python wall-time, `tracemalloc`, and SciPy edge-case verification.*

Although SciPy BCa fits inside NFR-02's 10-second wall-time cap (1.82 s for 60 cells, 3.65 s for 120 dual-regime cells), applying BCa to sample medians is mathematically fragile because its acceleration estimate relies on a leave-one-out jackknife, and a median's jackknife depends exclusively on the 2–3 central order statistics. Whenever timings are quantized or flat (such as synthetic zero-noise datasets in `UT-10`), identical center values collapse jackknife variance to zero, raising `DegenerateDataWarning`, `RuntimeWarning: invalid value encountered in scalar divide`, and `(nan, nan)` confidence bounds. Switching to analytical within-block paired log-ratio t-intervals (with a vectorized paired bootstrap available as an optional robustness check) sidesteps jackknife failure and cuts analysis time nearly 30-fold.

---

## Statistical and Mathematical Audit: Fixing FR-08, FR-11, FR-12, and ST-01

Draft 1.0's null-calibrated decision rule is well motivated, but its written specification contains four interacting mathematical defects that undermine ST-01, ST-02, and real-machine knee classification.

### Flaw 1: Scale and Unit Contradiction Across FR-11, FR-12, Section 7, and Section 9

Draft 1.0 defines $\delta$ inconsistently across four sections. Section 9 defines `null_distribution` as returning log ratios $\ln(T_A / T_B)$ (centered at 0.0, with 99th percentile ~0.033 at 1% per-trial noise), whereas Section 7's mock `summary.csv` lists linear ratios (`null_p99 = 1.03, 1.14`). Meanwhile, FR-11 defines `delta = 99th percentile of the A/A null ratio` and evaluates `CI_upper <= 1 + delta`: plugging a linear ratio (`1.03`) produces `1 + delta = 2.03` (a 103% slowdown threshold), whereas plugging a log ratio (`0.033`) breaks FR-12's `null_p99 > 1.10` inconclusive check because $\exp(1.10) = 3.00\times$ (a 200% noise spike). Even after unifying units so the threshold is cleanly $\tau_{AA} = Q_{0.99}(T_A / T_B)$ on the linear ratio scale, three deeper statistical flaws remain.

### Flaw 2: The 20.04× Variance-Scaling Mismatch and 2.90% CV Cliff (Calculation 5)

Model individual trial latencies with multiplicative noise $\ln T_i \sim \mathcal{N}(\mu, \sigma^2)$, where $\sigma$ is the per-trial coefficient of variation (CV). The log-standard deviation of a single A/A pair ratio $R_{AA} = T_A / T_B$ is $\text{SD}[\ln R_{AA}] = \sqrt{2}\,\sigma = 1.4142\,\sigma$. For a 30-trial median ratio $R_{\text{med}} = \text{median}(T_{s,1..30}) / \text{median}(T_{256,1..30})$, the exact finite-sample variance of a standard normal sample median at $n = 30$ is 0.04990 (slightly below the asymptotic $\pi / 60 = 0.05236$), yielding:

$$\text{SD}[\ln R_{\text{med}}] = \sqrt{2 \times 0.04990}\,\sigma = 0.3159\,\sigma, \qquad \frac{\text{Var}[\ln R_{AA}]}{\text{Var}[\ln R_{\text{med}}]} = \left(\frac{1.4142}{0.3159}\right)^2 = 20.04\times$$

Calibrating a 30-trial aggregate ratio against a single-pair 99th percentile ($\tau_{AA} = \exp(z_{0.99}\sqrt{2}\,\sigma) = \exp(3.2900\,\sigma)$) inflates the noise bar by 4.48× in standard deviation (20.04× in variance). This mismatch triggers two severe failures. First, solving $\exp(3.2900\,\sigma^*) = 1.10$ reveals that FR-12's `null_p99 > 1.10` cutoff trips at a per-trial CV of just $\sigma = 2.90\%$. In 1,000-simulation Monte Carlo runs of ST-02 (10% true slowdown), FR-12 discards 46.3% of runs at 3.0% CV, 91.1% at 3.5% CV, and 99.6% at 4.0% CV as inconclusive, even though 30 paired trials on that same host achieve 100.0% power to detect a 10% slowdown and 92.4–99.8% power to detect a 5% slowdown. Second, at a realistic 2.0% per-trial CV, Draft FR-11 requires a 6.34% slowdown to achieve 90% detection power (`MDE90`) and has 0.0% power for a 3% effect and 23.2% power for a 5% effect—blinding it to subtle H1 prefetcher penalties—whereas paired-block Holm-Bonferroni inference reaches 99.1% power at 3% and 100.0% power at 5% (`MDE90` = 2.34% under the normal power approximation, or 2.36% using exact $t_{29, 0.90}$, dropping to 1.66% when within-block drift correlation $\rho = 0.5$).

| Per-Trial CV ($\sigma$) | Single-Pair `null_p99` ($\tau_{AA}$) | FR-12 Status (>1.10?) | FR-11 MDE90 | Paired-Block 6-Test Bonferroni MDE90 ($\rho = 0$) | Power @ 3% (FR-11 vs Paired) | Power @ 5% (FR-11 vs Paired) | Conclusive ST-02 MC Power @ 10% (FR-11 vs Paired) |
| :---: | :---: | :--- | :---: | :---: | :---: | :---: | :---: |
| 0.5% | 1.0166 | Conclusive | 1.55% | 0.58% | 100.0% vs 100.0% | 100.0% vs 100.0% | — |
| 1.0% | 1.0334 | Conclusive | 3.12% | 1.16% | 81.7% vs 100.0% | 100.0% vs 100.0% | 100.0% vs 100.0% |
| 2.0% | 1.0680 | Conclusive | 6.34% | 2.34% (2.36% exact $t$) | 0.0% vs 99.1% | 23.2% vs 100.0% | 100.0% vs 100.0% |
| 2.5% | 1.0857 | Borderline (3.5% inc.) | 7.99% | 2.93% | — | — | 96.5% vs 100.0% |
| 3.0% | 1.1037 | Inconclusive | 9.67% | 3.53% | 0.0% vs 72.4% | 0.0% vs 99.8% | 53.5% vs 100.0% |
| 4.0% | 1.1406 | Inconclusive | 13.09% | 4.74% | 0.0% vs 38.8% | 0.0% vs 92.4% | 0.4% vs 100.0% |
| 5.0% | 1.1788 | Inconclusive | 16.62% | 5.95% | 0.0% vs 20.8% | 0.0% vs 71.3% | 0.0% vs 100.0% |
| 7.0% | 1.2590 | Inconclusive | 24.02% | 8.43% | 0.0% vs 7.8% | 0.0% vs 33.2% | 0.0% vs 97.4% (analyt.) |
| 10.0% | 1.3896 | Inconclusive | 36.01% | 12.26% | 0.0% vs 3.1% | 0.0% vs 11.8% | 0.0% vs 68.5% (analyt.) |

*Calculation 5 source: Analytical power/MDE formulas (`z_90 = 1.2816` in the multi-CV table; `t_{29,0.90} = 1.311` shifts MDE90 at 2% CV by +0.02 percentage points from 2.34% to 2.36%) and 1,000-simulation Monte Carlo ST-02 verification (`B = 30` trials, 200 A/A pairs; `Bonf6` = 6-comparison Bonferroni).*

### Flaw 3: The FR-11 Direction Paradox and Multi-Comparison FWER Inflation

FR-11 defines the knee as the smallest stride whose CI upper bound is `<= 1 + delta`, which equivalently flags stride $s$ as contended whenever $\text{CI}_{\text{upper}}(s) > \tau$. This confuses a non-inferiority bound with a superiority test against noise. If an implementer repairs Flaw 2 by matching $\tau$ to the 30-trial median null 99th percentile ($\ln \tau_{\text{matched}} = 2.32635 \cdot \text{SE}_{\text{med}}$) while keeping FR-11's `CI_upper <= tau` inequality, the false-positive rate under the true null ($H_0$) collapses into a severe error:

$$P(\text{CI}_{\text{upper}} > \tau_{\text{matched}} \mid H_0) = P(Z + 1.96 > 2.32635) = P(Z > 0.3664) = 35.70\%$$

Across 6 non-reference strides on one curve, family-wise error rate (FWER) surges to $1 - (1 - 0.3570)^6 = 92.94\%$. Even with a properly oriented one-sided test at uncorrected per-test $\alpha$, evaluating 5–6 strides per curve across 5 thread counts and 2 placements (50–60 simultaneous comparisons on a 16-core host) inflates FWER substantially: at $\alpha = 0.05$, FWER reaches 26.49% per 6-stride curve and 95.39% across 60 tests; even at $\alpha = 0.01$, FWER is 5.85% per curve and 45.28% across 60 tests. Explicit multiplicity correction (Holm-Bonferroni across the primary family at family-wise $\alpha = 0.01$) is therefore essential.

### Flaw 4: Exact Order-Statistic Instability of ST-01 (Calculation 6)

Draft 1.0 collects at least $M = 200$ A/A pairs per thread count, and ST-01 validates calibration by splitting those pairs 50/50 (100 calibration, 100 held-out test) and requiring that at most 2% of held-out pairs exceed the calibrated 99th percentile. By exact distribution-free order-statistic theory, for any continuous null distribution $F$, the true tail probability above the $k$-th order statistic $X_{(k)}$ follows $p = 1 - F(X_{(k)}) \sim \text{Beta}(m_{\text{cal}} - k + 1,\, k)$, so the held-out exceedance count $Y$ follows an exact Beta-Binomial distribution:

$$P(Y = y) = \binom{n_{\text{test}}}{y} \frac{B(y + \alpha,\, n_{\text{test}} - y + \beta)}{B(\alpha, \beta)}, \qquad \alpha = m_{\text{cal}} - k + 1,\; \beta = k$$

NumPy's default `np.quantile(x, 0.99, method='linear')` interpolates at 1-based rank $r = 0.99(m_{\text{cal}} - 1) + 1$. At $m_{\text{cal}} = 100$, $r = 99.01$, placing 99% weight on $X_{(99)}$ where expected tail exceedance is $2/101 = 1.98\%$—nearly double the nominal 1%. On pure i.i.d. noise with a bug-free implementation, ST-01 fails 31.06% of the time (30.99% Monte Carlo on LogNormal, 30.14% on heavy-tailed $t_4$), causing almost 1 in 3 CI runs to fail spuriously; even switching to `method='higher'` ($k = 100$, sample maximum) still produces a 12.31% exact failure rate (12.79% LogNormal MC).

| Total A/A Pairs $M$ (50/50 Split) | `linear` Rank $r$ / $k_{\text{lo}}$ / $k_{\text{hi}}$ | Exact $P(\text{ST-01 Fail} > 2\%)$ (`linear`) | MC Fail Rate (`linear`, LogNormal / $t_4$) | Exact $P(\text{ST-01 Fail} > 2\%)$ (`higher`) | Full-Sample $P(\text{true } p > 2\%)$ (no split, $k = \lceil 0.99 M \rceil$) |
| :---: | :---: | :---: | :---: | :---: | :---: |
| 200 (Draft Spec) (100/100) | 99.01 / 99 / 100 | 31.06% | 30.99% / 30.14% | 12.31% | 23.51% (95% CI: 0.31–3.57%) |
| 400 (200/200) | 198.01 / 198 / 199 | 22.45% | 22.45% / 22.31% | 10.76% | 9.73% (95% CI: 0.41–2.54%) |
| 600 (300/300) | 297.01 / 297 / 298 | 16.98% | 16.58% / 16.55% | 8.82% | 4.43% ($\le 5\%$ at $M \ge 530$) |
| 1,000 (500/500) | 495.01 / 495 / 496 | 10.32% | 10.03% / 10.22% | 5.79% | 1.02% (95% CI: 0.55–1.83%) |
| 1,600 (800/800) | 792.01 / 792 / 793 | 5.25% | 5.00% / 5.16% | 3.10% | <0.18% (0.18% at $M = 1,500$) |
| 2,000 (1000/1000) | 990.01 / 990 / 991 | 3.43% ($\le 5\%$ at $M \ge 1,800$) | 3.33% / 3.29% | 2.06% | 0.03% (95% CI: 0.65–1.54%) |

*Calculation 6 source: Exact Beta-Binomial evaluation and 20,000-repetition Monte Carlo verification.*

Holding Draft 1.0's split-half ST-01 spurious failure probability below 5% would require $M = 1,200$ (`higher`) to $M = 1,800$ (`linear`) A/A pairs per thread count—imposing 10–30 minutes of extra runtime per sweep.

### The Replacement Decision Rule: Paired-Block Log-Ratio Holm-Bonferroni with MDE Gate

In every randomized block $b \in \{1, \dots, B\}$ (default $B = 30$, after discarding block 0 as warm-up), execute all 7 strides plus one paired A/A sentinel (`256_B`, a second stride-256 measurement with `role=sentinel` in `raw.csv`) in seeded Fisher-Yates order (`order = 0, 1, ...`). Using `ns_per_op` ($y_{s,b}$) from 50 ms time-capped cells, compute within-block paired log-ratios against that block's own stride-256 reference ($d_{256\_B, b} = \ln(y_{256\_B, b} / y_{256, b})$ for the sentinel):

$$d_{s,b} = \ln\!\left(\frac{y_{s,b}}{y_{256,b}}\right), \qquad \bar{d}_s = \frac{1}{B}\sum_{b=1}^{B} d_{s,b}, \qquad s_{d,s} = \sqrt{\frac{1}{B-1}\sum_{b=1}^{B}(d_{s,b} - \bar{d}_s)^2}$$

Within-block pairing cancels slow thermal throttling, frequency scaling, and background drift ($\text{Var}(d_{s,b}) = 2\sigma^2(1 - \rho)$ for within-block correlation $\rho \ge 0$). Compute the one-sided paired t-statistic $t_s = \bar{d}_s / (s_{d,s} / \sqrt{B})$ and exact right-tail p-value $p_s = 1 - F_{t, B-1}(t_s)$ across the canonical primary family of **$m = 5$** strides (`8, 16, 32, 64, 128` vs `256` on `cores`/`spread` at max threads for `atomic` and `coupled-pair`; stride `512`, `volatile`, `rw-asymmetric`, `smt-sibling`, and `t < max` are exploratory), apply Holm-Bonferroni adjustment at family-wise $\alpha = 0.01$, and compute the empirical 90%-power MDE fraction directly from the block-paired noise:

$$\text{MDE}_{90}(s) = \exp\!\left[\left(t_{B-1,\, 1 - \alpha_{\text{FW}}/m} + t_{B-1,\, 0.90}\right)\frac{s_{d,s}}{\sqrt{B}}\right] - 1$$

The canonical decision procedure maps directly to FR-11 and FR-12 (`Spec v2.0.md` and `decisions.md`):

- **Inconclusive Noise Gate:** `mde90` is stored internally as a fraction (`exp(...) - 1`) and serialized as `mde90_pct = 100 * mde90` in `summary.json`/`summary.csv` and `report.md`. If the paired A/A sentinel exhibits `mde90(256_B) > 0.10` (or `> 0.05` when `--strict-h1` is passed for H1-specific tests), classify the configuration as `inconclusive`.
- **Contended Stride Detection:** Flag stride $s$ as contended iff its Holm-adjusted $p_s^{\text{adj}} \le 0.01$ and its point slowdown $\exp(\bar{d}_s) - 1 > 0.01$ (a 1% practical floor preventing sub-1% micro-artifacts from shifting knees).
- **Simultaneous 99% Intervals:** Compute Bonferroni-adjusted 99% simultaneous confidence bands via `scipy.stats.t.ppf(1 - 0.01 / (2 * m), B - 1)` ($m = 5$, i.e., `0.999` per-interval quantile) and convert to percentage via `(exp(bound) - 1) * 100`.
- **Knee Estimation and Classification:** Report `knee = s*` where `s*` is the smallest stride such that `s*` itself is uncontended AND every stride `s > s*` is uncontended (no stride `s >= s*` is contended). Classify `flat` if no stride is contended, `line64` if $s^* \le 64$, `pair128` if $s^* = 128$, and `wider` if $s^* \ge 256$. If a statistically significant speedup (`512 < 256`, left-tail $p \le 0.01$ and effect $< -1\%$) or non-monotone contention pattern occurs, classify as `irregular`, set `knee_bytes = None`, and emit `log.warning("faster-wider detected at stride %d; not a knee", s)` for `512 < 256`. Exploratory configurations (`volatile`, `smt-sibling`, `rw-asymmetric`, `t < max`) emit their own descriptive `class` and `knee_bytes` in the exploratory table (`primary = false`).
- **Updated ST-01 & ST-02 Calibration Check:** Verify in CI (`make test-sim`) that the paired Holm-Bonferroni rule keeps global FWER $\le 1.5\%$ across **2,000** synthetic null sweeps (`ST-01`, nominal 1%) and achieves $\ge 90\%$ per-stride detection power at stride 64 across **1,000** sweeps with a 5% slowdown injected at stride 64 only (`ST-02`). Flag `drift_alert` on real runs if the paired sentinel `256_B` fails a two-sided zero-mean t-test ($p \le 0.01$) or displays lag-1 autocorrelation ($|r_1| > 2 / \sqrt{B}$)—aligning with Kalibera and Jones's steady-state independence diagnostics.

| Noise Family (5,000 MC Validation Sweeps, $B = 30$, $m = 6$, FWER Target $\le 1.0\%$) | Block Corr. ($\rho$) | Observed Global FWER | Power @ 3% | Power @ 5% | Power @ 10% | Max $\sigma$ for MDE90 $\le 10\%$ |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| Gaussian ($\sigma = 2.0\%$) | 0.0 | 0.98% | 99.2% | 100.0% | 100.0% | 8.19% (vs 2.90% draft) |
| Gaussian ($\sigma = 2.0\%$) | 0.3 | 0.84% | 100.0% | 100.0% | 100.0% | 9.79% (11.58% at $\rho = 0.5$) |
| Heavy-tailed Student-$t_4$ (SD = 2.0%) | 0.0 | 0.90% | 97.8% | 99.9% | 100.0% | ~8.2% |
| Heavy-tailed Student-$t_4$ (SD = 2.0%) | 0.3 | 0.94% | 99.4% | 99.9% | 100.0% | ~9.8% |
| Right-skewed OS-interrupt spikes (8% rate, ~2.4% SD) | 0.0 | 0.38% | 91.0% | 99.3% | 100.0% | Conservative (safe) |
| Right-skewed OS-interrupt spikes (8% rate, ~2.4% SD) | 0.3 | 0.24% | 95.8% | 99.9% | 100.0% | Conservative (safe) |

*Monte Carlo source: 5,000-repetition sensitivity study at $m = 6$ (under canonical $m = 5$, critical thresholds are slightly more sensitive).*

Because within-block differences $d_{s,b} = \ln(y_{s,b}) - \ln(y_{256,b})$ remain symmetric under the null even when raw latencies suffer right-skewed OS interrupt spikes, the paired t-test stays conservative across heavy-tailed and spiky noise (0.24–0.98% FWER) while preserving >91% power down to a 3% slowdown.

---

## Closing Specification Gaps: Toolchains, Licenses, Literature, and Folklore

### Verified Dependency Matrix (As of 27 November 2026)

Every unverified `[U]` or stale April–August 2026 entry from Draft 1.0 has been verified against official release pages as of 27 November 2026:

| Component | Draft 1.0 Value | Verified Latest (as of 27 Nov 2026) | Implementation / CI Action |
| :--- | :--- | :--- | :--- |
| GCC | 16.2 / 14.4 (26 Jun) | GCC 16.2 (7 Aug 2026); 15.3 (12 Jun 2026); 14.4 (19 Jun 2026) | Correct 14.4 release date to 19 Jun 2026; GCC 17.0 is in development. |
| Clang / LLVM | 22.1.8; 23.1.x unverified | LLVM 23.1.6 (16–17 Nov 2026; 23.1.7 scheduled 1 Dec 2026) | Pin 23.1.6 where available; LLVM 23 added `-Wunused-template` to `-Wall` (benign for C11). |
| Python | 3.14.7; 3.15 RC | Python 3.15.2 and 3.14.10 (both 25 Oct 2026; 3.15.0 GA 9 Oct 2026) | Add 3.15 to CI (`actions/python-versions` added 3.15 on 10 Oct 2026); avoid 3.14.7–3.14.9 / 3.15.0–3.15.1 due to October 2026 security/cert fixes. |
| NumPy | 2.4.5 (Apr 2026) | NumPy 2.5.5 (15 Nov 2026; requires Python >= 3.12) | Full wheel support including CPython 3.15. |
| pandas | 3.0.3 (Apr 2026) | Dropped (D8) | Drop `pandas` entirely; use stdlib `csv` + NumPy to cut CI wheel footprint and avoid CoW changes. |
| Matplotlib | 3.10.9 (Apr 2026) | Matplotlib 3.11.2 (11 Sep 2026; CPython 3.15 wheels available) | Pin `matplotlib==3.11.2` in `requirements.lock`. |
| SciPy | Unverified | SciPy 1.18.1 (21 Aug 2026; CPython 3.15 wheels available) | Pin `scipy==1.18.1`; lightweight usage (`scipy.stats.t`). |
| pytest / ruff | Unverified | `pytest 9.2.0` (27 Oct 2026, native subtests since 9.0); `ruff 0.17.6` (19 Nov 2026) | Pin both exact versions in CI. |
| GitHub Actions | `checkout@v6`, `setup-python@v6`, `upload-artifact@v5` | `actions/checkout@v7.0.1`, `actions/setup-python@v6.3.0`, `actions/upload-artifact@v7.0.2` (7 Oct 2026) | Critical fix: `upload-artifact@v5` ran on Node.js 20 (removed from runners Sep 2026); `v7.0.2` uses Node.js 24. Pin all actions by full commit SHA with version comment in workflows. |
| Runner Images | `ubuntu-24.04` / `26.04` + `-arm` | Confirmed GA (`ubuntu-latest` finished migrating to 26.04 on 19 Nov 2026); 4 vCPU / 16 GB RAM free on public repos (x64 & arm64) | Note standard Linux runners can land on either Azure or AWS compute, making hypervisor/CPU model capture in `meta.json` vital for H3. |

### License Clearance and Verified Related-Work Citations

Auditing upstream repositories resolves the legal and bibliographic gaps from Draft 1.0:

- **Permissive / referenceable:** `crossbeam-utils` (v0.8.23, 28 Oct 2026) is dual-licensed `MIT OR Apache-2.0`; `facebook/folly` (`Align.h`) is `Apache-2.0`; `perfgo/perfgo` is `Apache-2.0`.
- **Do not copy:** `plasma-umass/sheriff` (strict `GPL-2.0` copyleft, incompatible with MIT), `khale/false-sharing` (no license file present, all rights reserved by default), and `joemario/perf-c2c-usage-files` (license unconfirmed; repository inaccessible during audit).
- **Academic tools:** `efeslab/huron` is confirmed public on GitHub (238 commits, CMake/LLVM/VMDK artifact, though its README omits a license statement); `plasma-umass/Predator` is cited in community threads but its GitHub URL was inaccessible. Implementing `src/*.c` cleanly from scratch avoids all licensing risk.
- **Verified publication records:**
  - Georges, Buytaert, and Eeckhout, *"Statistically Rigorous Java Performance Evaluation,"* OOPSLA 2007, pp. 57–76 (DOI `10.1145/1297027.1297033`).
  - Mytkowicz, Diwan, Hauswirth, and Sweeney, *"Producing Wrong Data Without Doing Anything Obviously Wrong!,"* ASPLOS 2009, pp. 265–276 (DOI `10.1145/1508284.1508275`).
  - Kalibera and Jones, *"Rigorous Benchmarking in Reasonable Time,"* ISMM 2013, pp. 63–74 (DOI `10.1145/2464157.2464160`).
  - David, Guerraoui, and Trigonakis (SOSP 2013, pp. 33–48) for multi-socket hardware cache-coherence latency characterization.
  - Patel, Biswas, and Chaudhuri (MICRO 2024, pp. 823–839, DOI `10.1109/MICRO61859.2024.00066`) for FSDetect/FSLite.
  - Feng Tang's February 2023 Linux `perf c2c --double-cl` patch; CPython `gh-144438` (Feb 2026) and Issue `#159860` (Oct 2026) documented as distinct bugs in `docs/related-work.md`.

### Expanding FR-14: The Seven-Ecosystem Folklore Contradiction Matrix

Comparing padding constants across seven major ecosystems—`crossbeam-utils`, `Facebook Folly`, `HotSpot JVM` (`@Contended` / JEP 142), `Go runtime` (`CacheLinePadSize`), `Linux kernel` (`L1_CACHE_BYTES`), `C++17 std::hardware_destructive_interference_size` (GCC and LLVM 21+), and `CPython 3.15` QSBR fixes—reveals 2×–4× disagreements: on x86-64, ecosystems split between 64 B and 128 B; on generic AArch64, values span 64 B to 256 B (set by GCC and LLVM 21+ for Fujitsu A64FX); and on s390x, Crossbeam pads to 256 B whereas Folly's fallback ternary `(kIsArchArm || kIsArchS390X) ? 64 : 128` in `folly/lang/Align.h` selects 64 B.

---

## Phase 2 Extensions (Post-Gate G1)

### Causal Hardware Prefetcher Ablation (`scripts/msr_ablate.sh`, Phase 2 / T15)

Draft 1.0 treats "prefetcher BIOS state unknown" as an unavoidable limitation (`NFR-08`). Adding an optional privileged sidecar script (`scripts/msr_ablate.sh`, keeping `NFR-07`'s unprivileged default path intact and never called from `run_all.sh`) provides direct causal evidence on bare-metal Linux hosts via `msr-tools`:

- `--intel`: Targets Intel `MSR_MISC_FEATURE_CONTROL` (`0x1A4` bit 1 to disable L2 adjacent-line prefetcher; bit 0 L2 streamer, bit 2 L1 DCU streamer, bit 3 L1 DCU IP prefetcher).
- `--amd`: Targets AMD Zen 4/5 `MSR 0xC0000108` (`PrefetchControl`). On Zen 2 or unsupported CPUs, `msr_ablate.sh` exits with code `0` and prints `"MSR 0xC0000108 not supported on this CPU; Zen 4/5 only"`.
- Safety invariants: dry-run by default, explicit `--confirm` flag required, root required, and `trap` restore-on-exit (`EXIT INT TERM`) mandatory.

### Multi-ISA Hardware Atlas & Community Bundles (Phase 2 / T16–T20)

Once the Phase 1 3-machine pilot and Gate G1 pass, an MIT-licensed open-source project qualifies for free accounts on the GCC Compile Farm (`portal.cfarm.net`), alongside GitHub Actions, Oracle Cloud Always Free, and academic bare-metal testbeds:

| Platform & Cost | Available Target Hardware (Verified Nov 2026) | Hypotheses & Folklore Conflicts Tested |
| :--- | :--- | :--- |
| GCC Compile Farm (`portal.cfarm.net`, $0 OSS) | Bare-metal Intel Xeon E5-2620 v3 (`cfarm13/14`, 2 sockets, 12c/24t); Apple M1 Linux (`cfarm103`, 8c); Ampere eMAG (`cfarm185`, 32c) & Altra Max Neoverse-N1 VMs (`cfarm424–427`); NVIDIA GB10 (`cfarm107/108`, 20c) & Jetson Thor (`cfarm109`, 14c); IBM POWER10 (`cfarm120`, 24c/192t) & POWER9 (`cfarm135`); IBM s390x LinuxONE VMs (`cfarm191/192`, 8c); RISC-V VisionFive 2 (`cfarm93/94`) & Spacemit X60 (`cfarm95`, 8c); LoongArch (`cfarm400`, 32c). | Tests H1 on bare-metal Intel Xeon; tests H2 on bare-metal Apple M1 Linux (`64 B` `CTR_EL0` vs `128 B` knee) and ARM64; probes the 4× s390x Folly-vs-Crossbeam conflict (64 B vs 256 B) and verifies POWER10 (128 B) and RISC-V (64 B). |
| GitHub Actions ($0 public repos) | Standard `ubuntu-24.04`, `ubuntu-26.04`, `ubuntu-24.04-arm`, `ubuntu-26.04-arm` (4 vCPU / 16 GB RAM; Azure/AWS VMs). | Automated weekly H3 cloud-VM noise-envelope time series across x64 and arm64 hypervisors (`measure.yml`). |
| Oracle Cloud Always Free ($0 permanent) | Ampere A1 (Neoverse N1): 2 OCPUs / 12 GB RAM (1,500 OCPU-hrs/mo). | 2-thread Neoverse N1 cloud VM comparison against bare-metal ARM64 (H2 + H3). |
| CloudLab / Chameleon ($0 academic) | Bare-metal AMD EPYC, Intel Xeon-D, and 64-bit ARM servers. | Bare-metal AMD EPYC H1 comparison and `0xC0000108` ablation. |

In Phase 2, `make submit-bundle` validates `meta.json`, `raw.csv` (with `256_B` sentinel rows), `summary.json`, and `report.md` under `data/<arch>-<cpu-slug>-<UTC>/`, paired with `validate-data.yml` and `docs/atlas.md` + `figs/knee_by_machine.png` generation.

---

## Phased Implementation Roadmap

### Phase 1: MVP (`T00–T13` — Target: `make smoke`, `make test-sim`, and Local Pilot)

| Module | Files (5-File C Layout + Modular Python) | NFR-06 Cap | Canonical Details |
| :--- | :--- | :---: | :--- |
| **C Benchmark Kernel** | `src/main.c`, `src/topo.c`, `src/alloc.c`, `src/kernel.c`, `src/fs_stride.h` | <= 400 LOC | `posix_memalign(&ptr, 4096, round_up_4096(raw))` + `memset` + `atomic_init`; `sched_setaffinity` from `sysfs` (`cores`, `smt-sibling`, `spread`); `K = 65,536` loop (`barrier -> K ops -> barrier -> check`); `--mode atomic\|coupled-pair\|volatile\|rw-asymmetric`; 14-column `raw.csv` (`run_id,host,mode,stride,threads,placement,block,order,role,total_ops,elapsed_s,ns_per_op,cpus,loadavg1`). |
| **Python Analyzer & Report** | `analysis/fs_stride_analysis/{io,stats,classify,sim,folklore,report,cli}.py` | <= 600 LOC | Stdlib `csv`, `numpy`, `scipy.stats.t`, `matplotlib`, `tomllib`; paired log-ratio Holm-Bonferroni ($\alpha = 0.01$, $m = 5$, 1% floor, Bonferroni `ppf(1 - 0.01/(2*m), B-1)`); `mde90 > 0.10` gate (`0.05` with `--strict-h1`); `mde90_pct = 100 * mde90`; `s >= s*` uncontended knee + `512 < 256` `irregular` warning; 7-ecosystem `folklore.toml`; `curve_*.png` + `sentinel_hist.png`; exit codes `0..3`. |
| **Orchestration & MVP CI** | `scripts/{run_all,capture_meta}.sh`, `.github/workflows/{ci,measure}.yml` | Shellcheck clean | `run_all.sh` sets benchmark defaults; `capture_meta.sh` fills `meta.json`; `ci.yml` runs `-Werror`, `ruff`, `shellcheck`, `cloc` hard-fail, ASan/UBSan tests, `make test-asm`, `make test-sim`, `make smoke`, schema validation; `measure.yml` runs weekly (non-gating). |

- **Block 1 (C Core & Unit Tests):** Build `src/main.c`, `src/topo.c`, `src/alloc.c`, `src/kernel.c`, and `src/fs_stride.h` using `posix_memalign(&ptr, 4096, round_up_4096(raw))` + `memset`, `sched_setaffinity` (`cores`, `smt-sibling`, `spread`), and the `K = 65,536` chunked loop (`atomic`, `coupled-pair`, `volatile`, `rw-asymmetric`). Emit 14-column `raw.csv` with `role` (`ref`, `test`, `sentinel`) and `ns_per_op = elapsed_s * 1e9 * threads / total_ops`. Pass `UT-01`–`UT-06` and `UT-14` (`50–100 ms`), including `objdump -d` verification (`UT-04`) of `lock` (x86-64) or `ldadd`/`ldxr` (AArch64 with `-mno-outline-atomics`).
- **Block 2 (Python Analysis, Validation & `ci.yml`):** Build `analysis/fs_stride_analysis/` on `csv`, `numpy`, `scipy.stats.t`, and `matplotlib` using paired log-ratio Holm-Bonferroni ($\alpha = 0.01$, $m = 5$, 1% floor), `mde90 > 0.10` (`--strict-h1` `0.05`), Bonferroni `ppf(1 - 0.01/(2*m), B-1)`, `s >= s*` knee + `512 < 256` `irregular` warning, `drift_alert`, and the 7-ecosystem `data/folklore.toml`. Wire `pytest` coverage for `UT-07`–`UT-13`, `NT-01`–`NT-08`, and `ST-01` (2,000 null sweeps, FWER <= 1.5%) / `ST-02` (1,000 sweeps, power >= 90% at stride 64) / `ST-03`. Commit `.github/workflows/ci.yml` and `measure.yml` on `ubuntu-24.04`, `ubuntu-26.04`, `ubuntu-24.04-arm`, and `ubuntu-26.04-arm` using SHA-pinned actions (`checkout@v7.0.1`, `setup-python@v6.3.0`, `upload-artifact@v7.0.2`).
- **Block 3 (Pilot Validation):** Execute `make all` / `make sweep` locally on the pilot machine and validate Gates G0 and G1 (`data/` holds only the pilot run in MVP).

### Phase 2: Extensions (`T14–T20` — Post-Gate G1)

After Gate G1 passes on the local pilot: add `scripts/c2c_check.sh` (`T14` / `IT-06`), `scripts/msr_ablate.sh` (`T15` / `IT-07`, Intel `0x1A4` bit 1 + AMD `0xC0000108` Zen 4/5 only), `release.yml` + Zenodo DOI + `validate-data.yml` (`T16`), `resolve_pins.sh` + `dependabot.yml` (`T17`), `license_check.sh` (`T18`), `docs/atlas.md` + `figs/knee_by_machine.png` (`T19`), `paper/main.tex` (`T20`), and multi-ISA Compile Farm / CloudLab data collection.
