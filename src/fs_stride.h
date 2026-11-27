#ifndef FS_STRIDE_H
#define FS_STRIDE_H

#include <stddef.h>
#include <stdint.h>

#define FS_MAX_CPUS 1024
#define FS_MAX_STRIDES 32
#define FS_MAX_THREADS 16
#define FS_MAX_MODES 4
#define FS_MAX_PLACEMENTS 3
#define FS_DEFAULT_CHUNK_OPS 65536ULL
#define FS_DEFAULT_TARGET_MS 50.0
#define FS_DEFAULT_BLOCKS 30
#define FS_REF_STRIDE 256U

typedef enum { FS_MODE_ATOMIC = 0, FS_MODE_COUPLED_PAIR, FS_MODE_VOLATILE, FS_MODE_RW_ASYMMETRIC } fs_mode_t;
typedef enum { FS_PLACE_CORES = 0, FS_PLACE_SMT_SIBLING, FS_PLACE_SPREAD } fs_placement_t;
typedef enum { FS_ROLE_REF = 0, FS_ROLE_TEST, FS_ROLE_SENTINEL } fs_role_t;

typedef struct { int cpu_id, core_id, package_id, smt_rank, is_p_core, online; } cpu_info_t;
typedef struct {
    cpu_info_t cpus[FS_MAX_CPUS]; int n_cpus, n_physical_cores, n_packages, has_hybrid;
    char p_core_list[256], e_core_list[256];
} topo_t;
typedef struct {
    char run_id[64], host[64], sysfs_root[256];
    fs_mode_t modes[FS_MAX_MODES]; fs_placement_t placements[FS_MAX_PLACEMENTS];
    size_t strides[FS_MAX_STRIDES]; int threads[FS_MAX_THREADS];
    int n_modes, n_strides, n_threads, n_placements, blocks, sequential, oversubscribe, print_layout, print_meta;
    double target_ms; unsigned int seed;
} config_t;
typedef struct { fs_mode_t mode; size_t stride; int threads, block, order; fs_placement_t placement; fs_role_t role; } cell_t;
typedef struct { uint64_t total_ops; double elapsed_s, ns_per_op, last_chunk_s, loadavg1; int cpus[FS_MAX_CPUS], n_cpus; } result_t;

int parse_args(int argc, char **argv, config_t *cfg);
void make_schedule(cell_t *cells, size_t n_per_block, unsigned int seed, int blocks, int sequential);
void emit_row(const config_t *cfg, const cell_t *cell, const result_t *res);
int topo_load(topo_t *topo, const char *sysfs_root);
int topo_pick(const topo_t *topo, fs_placement_t placement, fs_mode_t mode, int threads, int oversubscribe, int *cpus_out);
int pin_to_cpu(int cpu);
size_t detect_line_size(const char *sysfs_root);
void *alloc_counters(size_t stride, int slots);
int check_stride(size_t stride, int max_threads, int *warn_aliasing_out);
result_t run_cell(fs_mode_t mode, size_t stride, int threads, const int *cpus, double target_s);
void print_layout(const void *base, size_t stride, int slots);
const char *fs_mode_str(fs_mode_t mode); const char *fs_placement_str(fs_placement_t placement); const char *fs_role_str(fs_role_t role);
#endif
