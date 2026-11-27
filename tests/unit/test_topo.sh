#!/usr/bin/env bash
set -euo pipefail
BIN="${FS_STRIDE_BIN:-./fs_stride}"

TMP_C="$(mktemp /tmp/test_topo_XXXXXX.c)"
TMP_BIN="/tmp/test_topo_helper"
trap 'rm -f "$TMP_C" "$TMP_BIN"' EXIT

cat >"$TMP_C" <<'EOF'
#include "fs_stride.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static void check_pick(const topo_t *t, fs_placement_t p, int thr, const char *exp) {
    int cpus[FS_MAX_CPUS];
    assert(topo_pick(t, p, FS_MODE_ATOMIC, thr, 0, cpus) == 0);
    char got[256] = {0};
    for (int i = 0; i < thr; i++) {
        char buf[16];
        snprintf(buf, sizeof(buf), "%s%d", i ? ";" : "", cpus[i]);
        strcat(got, buf);
    }
    if (strcmp(got, exp) != 0) {
        fprintf(stderr, "Mismatch placement=%d thr=%d: got=%s expected=%s\n",
                (int)p, thr, got, exp);
        assert(0);
    }
}

int main(void) {
    topo_t t;
    assert(topo_load(&t, "tests/fixtures/sysfs_smt_on") == 0);
    assert(t.n_physical_cores == 4 && t.n_packages == 1);
    check_pick(&t, FS_PLACE_CORES, 4, "0;1;2;3");
    check_pick(&t, FS_PLACE_SMT_SIBLING, 4, "0;4;1;5");
    check_pick(&t, FS_PLACE_SPREAD, 4, "0;1;2;3");

    assert(topo_load(&t, "tests/fixtures/sysfs_smt_off") == 0);
    assert(t.n_physical_cores == 4);
    check_pick(&t, FS_PLACE_CORES, 4, "0;1;2;3");
    check_pick(&t, FS_PLACE_SMT_SIBLING, 4, "0;1;2;3");
    check_pick(&t, FS_PLACE_SPREAD, 4, "0;1;2;3");

    assert(topo_load(&t, "tests/fixtures/sysfs_hybrid") == 0);
    assert(t.has_hybrid == 1 && t.n_physical_cores == 2);
    check_pick(&t, FS_PLACE_CORES, 2, "0;2");
    check_pick(&t, FS_PLACE_SMT_SIBLING, 4, "0;1;2;3");
    check_pick(&t, FS_PLACE_SPREAD, 2, "0;2");

    assert(topo_load(&t, "tests/fixtures/sysfs_dual_socket") == 0);
    assert(t.n_physical_cores == 4 && t.n_packages == 2);
    check_pick(&t, FS_PLACE_CORES, 4, "0;1;2;3");
    check_pick(&t, FS_PLACE_SMT_SIBLING, 4, "0;4;1;5");
    check_pick(&t, FS_PLACE_SPREAD, 4, "0;2;1;3");
    printf("UT-01 PASS\n");
    return 0;
}
EOF

"${CC:-gcc}" -O1 -g -std=c11 -Wall -Wextra -Werror -D_GNU_SOURCE -fsanitize=address,undefined -Isrc "$TMP_C" src/topo.c -o "$TMP_BIN" -lm
"$TMP_BIN"

META_HYB="$("$BIN" --sysfs-root tests/fixtures/sysfs_hybrid --print-meta)"
echo "$META_HYB" | grep -q '"p_core_cpus":"0-3"'
echo "$META_HYB" | grep -q '"e_core_cpus":"4-7"'
echo "$META_HYB" | grep -q '"physical_cores":2'

# NT-08: restricted cpuset via taskset with too few CPUs -> exit 3
set +e
taskset -c 0 "$BIN" --modes atomic --strides 8,256 --threads 2 --blocks 2 --target-ms 10 >/dev/null 2>&1
rc=$?
set -e
if [ "$rc" -ne 3 ]; then
    echo "NT-08 FAIL: expected exit 3 under taskset -c 0 with --threads 2, got $rc" >&2
    exit 1
fi
echo "NT-08 PASS"
