#include "fs_stride.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

const char *fs_mode_str(fs_mode_t m) { static const char *s[] = {"atomic", "coupled-pair", "volatile", "rw-asymmetric"}; return s[m]; }
const char *fs_placement_str(fs_placement_t p) { static const char *s[] = {"cores", "smt-sibling", "spread"}; return s[p]; }
const char *fs_role_str(fs_role_t r) { static const char *s[] = {"ref", "test", "sentinel"}; return s[r]; }

static int parse_csv(const char *arg, int (*fn)(const char *, config_t *), config_t *c) {
    char buf[512]; snprintf(buf, sizeof(buf), "%s", arg);
    for (char *tok = strtok(buf, ","); tok; tok = strtok(NULL, ",")) if (fn(tok, c)) return -1;
    return 0;
}
static int add_mode(const char *t, config_t *c) {
    for (int i = 0; i < 4 && c->n_modes < FS_MAX_MODES; i++)
        if (!strcmp(t, fs_mode_str((fs_mode_t)i))) { c->modes[c->n_modes++] = (fs_mode_t)i; return 0; }
    return -1;
}
static int add_place(const char *t, config_t *c) {
    for (int i = 0; i < 3 && c->n_placements < FS_MAX_PLACEMENTS; i++)
        if (!strcmp(t, fs_placement_str((fs_placement_t)i))) { c->placements[c->n_placements++] = (fs_placement_t)i; return 0; }
    return -1;
}
static int parse_pos(const char *t, long *v) { char *e = NULL; *v = strtol(t, &e, 10); return (*e || *v <= 0) ? -1 : 0; }
static int add_stride(const char *t, config_t *c) {
    long v; if (parse_pos(t, &v) || c->n_strides >= FS_MAX_STRIDES || check_stride((size_t)v, 1, NULL)) return -1;
    c->strides[c->n_strides++] = (size_t)v; return 0;
}
static int add_thread(const char *t, config_t *c) {
    long v; if (parse_pos(t, &v) || c->n_threads >= FS_MAX_THREADS) return -1;
    c->threads[c->n_threads++] = (int)v; return 0;
}

int parse_args(int argc, char **argv, config_t *cfg) {
    memset(cfg, 0, sizeof(*cfg)); gethostname(cfg->host, sizeof(cfg->host) - 1);
    snprintf(cfg->run_id, sizeof(cfg->run_id), "%.40s-%ld", cfg->host, (long)time(NULL));
    cfg->target_ms = FS_DEFAULT_TARGET_MS; cfg->blocks = FS_DEFAULT_BLOCKS; cfg->seed = 42U;
    for (int i = 1; i < argc; i++) {
        const char *a = argv[i], *nx = (i + 1 < argc) ? argv[i + 1] : NULL;
        if (nx && !strcmp(a, "--modes")) { if (parse_csv(argv[++i], add_mode, cfg)) return 2; }
        else if (nx && !strcmp(a, "--strides")) { if (parse_csv(argv[++i], add_stride, cfg)) return 2; }
        else if (nx && !strcmp(a, "--threads")) { if (parse_csv(argv[++i], add_thread, cfg)) return 2; }
        else if (nx && !strcmp(a, "--placements")) { if (parse_csv(argv[++i], add_place, cfg)) return 2; }
        else if (nx && !strcmp(a, "--target-ms")) cfg->target_ms = atof(argv[++i]);
        else if (nx && !strcmp(a, "--blocks")) cfg->blocks = atoi(argv[++i]);
        else if (nx && !strcmp(a, "--seed")) cfg->seed = (unsigned int)strtoul(argv[++i], NULL, 10);
        else if (nx && !strcmp(a, "--run-id")) snprintf(cfg->run_id, sizeof(cfg->run_id), "%s", argv[++i]);
        else if (nx && !strcmp(a, "--host")) snprintf(cfg->host, sizeof(cfg->host), "%s", argv[++i]);
        else if (nx && !strcmp(a, "--sysfs-root")) snprintf(cfg->sysfs_root, sizeof(cfg->sysfs_root), "%s", argv[++i]);
        else if (!strcmp(a, "--sequential")) cfg->sequential = 1;
        else if (!strcmp(a, "--oversubscribe")) cfg->oversubscribe = 1;
        else if (!strcmp(a, "--print-layout")) cfg->print_layout = 1;
        else if (!strcmp(a, "--print-meta")) cfg->print_meta = 1;
        else return 2;
    }
    if (!cfg->n_modes) parse_csv("atomic,coupled-pair,volatile,rw-asymmetric", add_mode, cfg);
    if (!cfg->n_strides) parse_csv("8,16,32,64,128,256,512", add_stride, cfg);
    if (!cfg->n_placements) add_place("cores", cfg);
    int has_ref = cfg->print_layout || cfg->print_meta;
    for (int i = 0; i < cfg->n_strides; i++) has_ref |= (cfg->strides[i] == FS_REF_STRIDE);
    return (!has_ref || cfg->blocks < 2 || cfg->target_ms <= 0.0) ? 2 : 0;
}

void make_schedule(cell_t *cells, size_t n_per_block, unsigned int seed, int blocks, int sequential) {
    if (!n_per_block) return;
    uint64_t rng = (uint64_t)seed + 1ULL;
    for (int b = 0; b <= blocks; b++) {
        cell_t *blk = cells + (size_t)b * n_per_block;
        for (size_t i = n_per_block - 1; !sequential && i > 0; i--) {
            uint64_t z = (rng += 0x9e3779b97f4a7c15ULL);
            z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9ULL; z = (z ^ (z >> 27)) * 0x94d049bb133111ebULL;
            size_t j = (size_t)((z ^ (z >> 31)) % (uint64_t)(i + 1));
            cell_t tmp = blk[i]; blk[i] = blk[j]; blk[j] = tmp;
        }
        for (size_t i = 0; i < n_per_block; i++) { blk[i].block = b; blk[i].order = (int)i; }
    }
}

void emit_row(const config_t *cfg, const cell_t *cell, const result_t *res) {
    printf("%s,%s,%s,%zu,%d,%s,%d,%d,%s,%llu,%.6f,%.4f,", cfg->run_id, cfg->host, fs_mode_str(cell->mode),
           cell->stride, cell->threads, fs_placement_str(cell->placement), cell->block, cell->order,
           fs_role_str(cell->role), (unsigned long long)res->total_ops, res->elapsed_s, res->ns_per_op);
    for (int i = 0; i < res->n_cpus; i++) printf("%s%d", i ? ";" : "", res->cpus[i]);
    printf(",%.2f\n", res->loadavg1);
}

int main(int argc, char **argv) {
    config_t cfg; topo_t topo;
    if (parse_args(argc, argv, &cfg)) return 2;
    if (topo_load(&topo, cfg.sysfs_root)) return 3;
    int auto_t = !cfg.n_threads, max_t = 1;
    if (auto_t) {
        for (int t = 1; t <= topo.n_physical_cores && cfg.n_threads < FS_MAX_THREADS; t *= 2) cfg.threads[cfg.n_threads++] = t;
        if (topo.n_physical_cores >= 2 && cfg.threads[cfg.n_threads - 1] != topo.n_physical_cores) cfg.threads[cfg.n_threads++] = topo.n_physical_cores;
    }
    for (int i = 0; i < cfg.n_threads; i++) {
        if (!cfg.oversubscribe && cfg.threads[i] > topo.n_physical_cores) return 2;
        if (cfg.threads[i] > max_t) max_t = cfg.threads[i];
    }
    if (cfg.print_meta) {
        int aw = 0; for (int i = 0; i < cfg.n_strides; i++) { int w = 0; check_stride(cfg.strides[i], max_t, &w); aw |= w; }
        printf("{\"seed\":%u,\"sysfs_coherency_line_size\":%zu,\"p_core_cpus\":\"%s\",\"e_core_cpus\":\"%s\",\"aliasing_warning\":%s,\"physical_cores\":%d}\n",
               cfg.seed, detect_line_size(cfg.sysfs_root), topo.p_core_list, topo.e_core_list, aw ? "true" : "false", topo.n_physical_cores);
        return 0;
    }
    if (cfg.print_layout) { void *p = alloc_counters(cfg.strides[0], max_t); if (!p) return 1; print_layout(p, cfg.strides[0], max_t); free(p); return 0; }
    size_t cap = (size_t)(cfg.n_modes * cfg.n_threads * cfg.n_placements * (cfg.n_strides + 1)), n_per = 0;
    cell_t *sched = calloc((size_t)(cfg.blocks + 1) * cap, sizeof(cell_t));
    for (int m = 0; m < cfg.n_modes; m++) for (int p = 0; p < cfg.n_placements; p++) for (int ti = 0; ti < cfg.n_threads; ti++) {
        int t = cfg.threads[ti];
        if (cfg.modes[m] == FS_MODE_COUPLED_PAIR && (t < 4 || (t % 2))) { if (!auto_t) { free(sched); return 2; } continue; }
        for (int si = 0; si < cfg.n_strides; si++)
            sched[n_per++] = (cell_t){cfg.modes[m], cfg.strides[si], t, 0, 0, cfg.placements[p], cfg.strides[si] == FS_REF_STRIDE ? FS_ROLE_REF : FS_ROLE_TEST};
        sched[n_per++] = (cell_t){cfg.modes[m], FS_REF_STRIDE, t, 0, 0, cfg.placements[p], FS_ROLE_SENTINEL};
    }
    if (!n_per) { free(sched); return 2; }
    for (int b = 1; b <= cfg.blocks; b++) memcpy(sched + (size_t)b * n_per, sched, n_per * sizeof(cell_t));
    make_schedule(sched, n_per, cfg.seed, cfg.blocks, cfg.sequential);
    printf("run_id,host,mode,stride,threads,placement,block,order,role,total_ops,elapsed_s,ns_per_op,cpus,loadavg1\n");
    for (size_t i = 0; i < (size_t)(cfg.blocks + 1) * n_per; i++) {
        int cpus[FS_MAX_CPUS];
        if (topo_pick(&topo, sched[i].placement, sched[i].mode, sched[i].threads, cfg.oversubscribe, cpus)) { free(sched); return 3; }
        result_t r = run_cell(sched[i].mode, sched[i].stride, sched[i].threads, cpus, cfg.target_ms / 1000.0);
        if (r.n_cpus < 0) { free(sched); return 3; }
        if (r.elapsed_s > 0.0 && (r.last_chunk_s / r.elapsed_s) > 0.25)
            fprintf(stderr, "warning: last_chunk/cell=%.3f > 0.25\n", r.last_chunk_s / r.elapsed_s);
        emit_row(&cfg, &sched[i], &r);
    }
    free(sched); return 0;
}
