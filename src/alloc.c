#include "fs_stride.h"
#include <stdlib.h>
#include <string.h>

void *alloc_counters(size_t stride, int slots) {
    size_t n = (slots > 0) ? (size_t)slots : 1U;
    size_t raw = stride * n;
    size_t sz = ((raw + 4095U) / 4096U) * 4096U;
    if (sz < 4096U) sz = 4096U;
    void *ptr = NULL;
    if (posix_memalign(&ptr, 4096U, sz) != 0) return NULL;
    memset(ptr, 0, sz);
    return ptr;
}

int check_stride(size_t stride, int max_threads, int *warn_aliasing_out) {
    if (stride == 0U || (stride % 8U) != 0U) return -1;
    if (warn_aliasing_out) {
        size_t t = (max_threads > 0) ? (size_t)max_threads : 1U;
        *warn_aliasing_out = (t * stride >= 4096U) ? 1 : 0;
    }
    return 0;
}
