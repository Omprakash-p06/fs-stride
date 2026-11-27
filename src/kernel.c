#include "fs_stride.h"
#include <omp.h>
#include <sched.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>

_Static_assert(ATOMIC_LLONG_LOCK_FREE == 2, "64-bit atomics must be lock-free");
#define NOINLINE __attribute__((noinline))

NOINLINE void chunk_atomic(_Atomic uint64_t *ctr) {
    for (uint64_t i = 0; i < FS_DEFAULT_CHUNK_OPS; i++) atomic_fetch_add_explicit(ctr, 1ULL, memory_order_relaxed);
}

NOINLINE void chunk_volatile_write(volatile uint64_t *ctr) {
    for (uint64_t i = 0; i < FS_DEFAULT_CHUNK_OPS; i++) { uint64_t v = *ctr; *ctr = v + 1ULL; }
}

NOINLINE uint64_t chunk_volatile_read(volatile uint64_t *ctr) {
    uint64_t acc = 0;
    for (uint64_t i = 0; i < FS_DEFAULT_CHUNK_OPS; i++) acc += *ctr;
    return acc;
}

result_t run_cell(fs_mode_t mode, size_t stride, int threads, const int *cpus, double target_s) {
    result_t res = {0};
    int slots = (mode == FS_MODE_COUPLED_PAIR) ? (threads / 2) : threads, aff_err = 0, stop = 0;
    uint8_t *buf = (uint8_t *)alloc_counters(stride, slots);
    if (!buf) { res.n_cpus = -1; return res; }
    if (mode == FS_MODE_ATOMIC || mode == FS_MODE_COUPLED_PAIR)
        for (int s = 0; s < slots; s++) atomic_init((_Atomic uint64_t *)(buf + (size_t)s * stride), 0ULL);

    double t_start = 0.0, elapsed = 0.0, last_chunk = 0.0;
    uint64_t total_ops = 0;
    #pragma omp parallel num_threads(threads) shared(buf, cpus, aff_err, stop, t_start, elapsed, last_chunk, total_ops, res)
    {
        int tid = omp_get_thread_num();
        if (pin_to_cpu(cpus[tid]) != 0) {
            #pragma omp atomic write
            aff_err = 1;
        }
        #pragma omp barrier
        if (!aff_err) {
            uint8_t *ptr = buf + ((mode == FS_MODE_COUPLED_PAIR) ? (size_t)(tid / 2) : (size_t)tid) * stride;
            volatile uint64_t sink = 0;
            uint64_t local_ops = 0;
            if (tid == 0) t_start = omp_get_wtime();
            #pragma omp barrier
            do {
                double c0 = (tid == 0) ? omp_get_wtime() : 0.0;
                if (mode == FS_MODE_ATOMIC || mode == FS_MODE_COUPLED_PAIR) chunk_atomic((_Atomic uint64_t *)ptr);
                else if (mode == FS_MODE_VOLATILE || (mode == FS_MODE_RW_ASYMMETRIC && tid == 0)) chunk_volatile_write((volatile uint64_t *)ptr);
                else sink += chunk_volatile_read((volatile uint64_t *)ptr);
                local_ops += FS_DEFAULT_CHUNK_OPS;
                #pragma omp barrier
                if (tid == 0) {
                    double now = omp_get_wtime();
                    last_chunk = now - c0; elapsed = now - t_start; stop = (elapsed >= target_s);
                }
                #pragma omp barrier
            } while (!stop);
            (void)sink;
            #pragma omp atomic
            total_ops += local_ops;
            res.cpus[tid] = sched_getcpu();
        }
    }
    free(buf);
    if (aff_err) { res.n_cpus = -1; return res; }
    res.total_ops = total_ops; res.elapsed_s = elapsed; res.last_chunk_s = last_chunk;
    res.ns_per_op = (elapsed * 1e9 * (double)threads) / (double)total_ops;
    res.n_cpus = threads;
    FILE *lf = fopen("/proc/loadavg", "r");
    if (lf) { if (fscanf(lf, "%lf", &res.loadavg1) != 1) res.loadavg1 = 0.0; fclose(lf); }
    return res;
}

void print_layout(const void *base, size_t stride, int slots) {
    for (int i = 0; i < slots; i++) {
        uintptr_t a = (uintptr_t)base + (uintptr_t)i * stride;
        printf("slot=%d addr=0x%zx line64=%zu chunk128=%zu\n", i, (size_t)a, (size_t)(a >> 6), (size_t)(a >> 7));
    }
}
