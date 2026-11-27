#include "fs_stride.h"
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

int main(void) {
    uint8_t *b8 = (uint8_t *)alloc_counters(8, 4);
    assert(b8 != NULL);
    for (int i = 1; i < 4; i++) {
        assert((((uintptr_t)(b8 + i * 8)) >> 6) == (((uintptr_t)b8) >> 6));
    }
    free(b8);

    uint8_t *b64 = (uint8_t *)alloc_counters(64, 4);
    assert(b64 != NULL);
    for (int i = 1; i < 4; i++) {
        assert((((uintptr_t)(b64 + i * 64)) >> 6) != (((uintptr_t)(b64 + (i - 1) * 64)) >> 6));
    }
    assert((((uintptr_t)(b64 + 0 * 64)) >> 7) == (((uintptr_t)(b64 + 1 * 64)) >> 7));
    assert((((uintptr_t)(b64 + 2 * 64)) >> 7) == (((uintptr_t)(b64 + 3 * 64)) >> 7));
    assert((((uintptr_t)(b64 + 0 * 64)) >> 7) != (((uintptr_t)(b64 + 2 * 64)) >> 7));
    free(b64);

    uint8_t *b128 = (uint8_t *)alloc_counters(128, 4);
    assert(b128 != NULL);
    for (int i = 1; i < 4; i++) {
        assert((((uintptr_t)(b128 + i * 128)) >> 7) != (((uintptr_t)(b128 + (i - 1) * 128)) >> 7));
    }
    print_layout(b128, 128, 4);
    free(b128);
    printf("UT-03 PASS\n");
    return 0;
}
