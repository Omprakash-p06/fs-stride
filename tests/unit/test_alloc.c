#include "fs_stride.h"
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

int main(void) {
    size_t strides[] = {8, 64, 256, 512};
    int slots_list[] = {1, 3, 5, 17};
    for (int i = 0; i < 4; i++) {
        size_t s = strides[i];
        int slots = slots_list[i];
        uint8_t *p = (uint8_t *)alloc_counters(s, slots);
        assert(p != NULL);
        assert(((uintptr_t)p % 4096U) == 0);
        size_t raw = (size_t)slots * s;
        size_t rounded = ((raw + 4095U) / 4096U) * 4096U;
        assert(rounded % 4096U == 0);
        for (size_t j = 0; j < rounded; j++) assert(p[j] == 0);
        free(p);
    }
    int warn = 0;
    assert(check_stride(12, 4, &warn) != 0);
    assert(check_stride(4, 4, &warn) != 0);
    assert(check_stride(64, 4, &warn) == 0 && warn == 0);
    assert(check_stride(1024, 4, &warn) == 0 && warn == 1);
    printf("UT-02 PASS\n");
    return 0;
}
