#include "fs_stride.h"
#include <ctype.h>
#include <dirent.h>
#include <sched.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static int read_str(const char *path, char *buf, size_t cap) {
    FILE *f = fopen(path, "r");
    if (!f) return -1;
    int ok = (fgets(buf, (int)cap, f) != NULL);
    fclose(f);
    if (ok) buf[strcspn(buf, "\r\n")] = '\0';
    return ok ? 0 : -1;
}

static int parse_mask(const char *s, uint8_t *bm, int *min_id) {
    int cnt = 0, mn = FS_MAX_CPUS;
    for (const char *p = s; *p;) {
        while (*p && !isdigit((unsigned char)*p)) p++;
        if (!*p) break;
        char *end = NULL;
        long a = strtol(p, &end, 10), b = (*end == '-') ? strtol(end + 1, &end, 10) : a;
        p = end;
        for (long i = a; i <= b && i < FS_MAX_CPUS; i++)
            if (i >= 0) { bm[i] = 1; cnt++; if ((int)i < mn) mn = (int)i; }
    }
    if (min_id) *min_id = (cnt > 0) ? mn : 0;
    return cnt;
}

static void read_hybrid(const char *root, const char *sub, char *out, size_t cap) {
    char p[512];
    snprintf(p, sizeof(p), "%s/%s/cpus", root, sub);
    if (read_str(p, out, cap) != 0) { snprintf(p, sizeof(p), "%s/../%s/cpus", root, sub); read_str(p, out, cap); }
}

static int cmp_cpu(const void *a, const void *b) { return ((const cpu_info_t *)a)->cpu_id - ((const cpu_info_t *)b)->cpu_id; }

int topo_load(topo_t *topo, const char *sysfs_root) {
    const char *root = (sysfs_root && *sysfs_root) ? sysfs_root : "/sys/devices/system/cpu";
    int use_aff = !strcmp(root, "/sys/devices/system/cpu");
    cpu_set_t allowed;
    if (use_aff && sched_getaffinity(0, sizeof(allowed), &allowed) != 0) return -1;
    memset(topo, 0, sizeof(*topo));
    snprintf(topo->p_core_list, sizeof(topo->p_core_list), "unknown");
    snprintf(topo->e_core_list, sizeof(topo->e_core_list), "unknown");
    uint8_t p_bm[FS_MAX_CPUS] = {0};
    char pbuf[256] = {0}, ebuf[256] = {0}, path[512], buf[256];
    read_hybrid(root, "cpu_core", pbuf, sizeof(pbuf));
    read_hybrid(root, "cpu_atom", ebuf, sizeof(ebuf));
    if (pbuf[0]) {
        topo->has_hybrid = 1; parse_mask(pbuf, p_bm, NULL);
        snprintf(topo->p_core_list, sizeof(topo->p_core_list), "%s", pbuf);
        snprintf(topo->e_core_list, sizeof(topo->e_core_list), "%s", ebuf[0] ? ebuf : "none");
    }
    DIR *d = opendir(root);
    if (!d) return -1;
    for (struct dirent *ent; (ent = readdir(d)) != NULL && topo->n_cpus < FS_MAX_CPUS;) {
        if (strncmp(ent->d_name, "cpu", 3) || !isdigit((unsigned char)ent->d_name[3])) continue;
        char *end = NULL; long cid = strtol(ent->d_name + 3, &end, 10);
        if (*end || cid < 0 || cid >= FS_MAX_CPUS) continue;
        snprintf(path, sizeof(path), "%s/cpu%ld/online", root, cid);
        if (read_str(path, buf, sizeof(buf)) == 0 && atoi(buf) == 0) continue;
        cpu_info_t *ci = &topo->cpus[topo->n_cpus++];
        ci->cpu_id = (int)cid; ci->online = (!use_aff || CPU_ISSET((int)cid, &allowed)) ? 1 : 0;
        ci->is_p_core = topo->has_hybrid ? p_bm[cid] : 1;
        snprintf(path, sizeof(path), "%s/cpu%ld/topology/physical_package_id", root, cid);
        ci->package_id = (read_str(path, buf, sizeof(buf)) == 0) ? atoi(buf) : 0;
        snprintf(path, sizeof(path), "%s/cpu%ld/topology/core_cpus_list", root, cid);
        if (read_str(path, buf, sizeof(buf)) != 0) {
            snprintf(path, sizeof(path), "%s/cpu%ld/topology/thread_siblings_list", root, cid);
            if (read_str(path, buf, sizeof(buf)) != 0) snprintf(buf, sizeof(buf), "%ld", cid);
        }
        uint8_t sib[FS_MAX_CPUS] = {0};
        parse_mask(buf, sib, &ci->core_id);
        for (int i = 0; i < (int)cid; i++) ci->smt_rank += sib[i];
    }
    closedir(d);
    if (!topo->n_cpus) return -1;
    qsort(topo->cpus, (size_t)topo->n_cpus, sizeof(cpu_info_t), cmp_cpu);
    int pkgs[FS_MAX_CPUS], cores[FS_MAX_CPUS], np = 0, nc = 0;
    for (int i = 0; i < topo->n_cpus; i++) {
        const cpu_info_t *c = &topo->cpus[i];
        int j = 0, k = 0, key = (c->package_id << 16) | (c->core_id & 0xFFFF);
        while (j < np && pkgs[j] != c->package_id) j++;
        if (j == np) pkgs[np++] = c->package_id;
        while (c->is_p_core && k < nc && cores[k] != key) k++;
        if (c->is_p_core && k == nc) cores[nc++] = key;
    }
    topo->n_packages = np ? np : 1; topo->n_physical_cores = nc;
    return 0;
}

static const topo_t *g_topo = NULL;
static int cmp_pick(const void *pa, const void *pb) {
    const cpu_info_t *a = &g_topo->cpus[*(const int *)pa], *b = &g_topo->cpus[*(const int *)pb];
    if (a->package_id != b->package_id) return a->package_id - b->package_id;
    if (a->core_id != b->core_id) return a->core_id - b->core_id;
    return (a->smt_rank != b->smt_rank) ? (a->smt_rank - b->smt_rank) : (a->cpu_id - b->cpu_id);
}

int topo_pick(const topo_t *topo, fs_placement_t placement, fs_mode_t mode, int threads, int oversubscribe, int *cpus_out) {
    (void)mode;
    int idx[FS_MAX_CPUS], n = 0;
    for (int i = 0; i < topo->n_cpus; i++)
        if (topo->cpus[i].online && topo->cpus[i].is_p_core && (placement == FS_PLACE_SMT_SIBLING || !topo->cpus[i].smt_rank)) idx[n++] = i;
    if (!n || (!oversubscribe && n < threads)) return -1;
    g_topo = topo; qsort(idx, (size_t)n, sizeof(int), cmp_pick);
    if (placement == FS_PLACE_SPREAD && topo->n_packages > 1) {
        int picked[FS_MAX_CPUS], used[FS_MAX_CPUS] = {0}, out = 0;
        for (int prog = 1; out < n && prog;) {
            int last_pkg = -1; prog = 0;
            for (int i = 0; i < n; i++)
                if (!used[i] && topo->cpus[idx[i]].package_id != last_pkg) { used[i] = 1; picked[out++] = idx[i]; last_pkg = topo->cpus[idx[i]].package_id; prog = 1; }
        }
        memcpy(idx, picked, (size_t)out * sizeof(int)); n = out;
    }
    for (int t = 0; t < threads; t++) cpus_out[t] = topo->cpus[idx[t % n]].cpu_id;
    return 0;
}

int pin_to_cpu(int cpu) { cpu_set_t s; CPU_ZERO(&s); CPU_SET(cpu, &s); return sched_setaffinity(0, sizeof(s), &s) ? -1 : 0; }

size_t detect_line_size(const char *sysfs_root) {
    const char *root = (sysfs_root && *sysfs_root) ? sysfs_root : "/sys/devices/system/cpu";
    char path[512], buf[64];
    snprintf(path, sizeof(path), "%s/cpu0/cache/index0/coherency_line_size", root);
    if (read_str(path, buf, sizeof(buf)) == 0 && atoi(buf) > 0) return (size_t)atoi(buf);
    long sc = sysconf(_SC_LEVEL1_DCACHE_LINESIZE);
    return (sc > 0) ? (size_t)sc : 64U;
}
