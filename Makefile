CC ?= gcc
UNAME_M := $(shell uname -m)
ARCH_CFLAGS := $(if $(filter aarch64,$(UNAME_M)),-mno-outline-atomics,)
CFLAGS := -O2 -fopenmp -std=c11 -Wall -Wextra -Werror -D_GNU_SOURCE $(ARCH_CFLAGS)
SAN_CFLAGS := -O1 -g -fopenmp -std=c11 -Wall -Wextra -Werror -D_GNU_SOURCE -fsanitize=address,undefined -fno-omit-frame-pointer $(ARCH_CFLAGS)

PYTHON := $(shell if [ -x .venv/bin/python3 ]; then echo .venv/bin/python3; else echo python3; fi)
PYTEST := $(PYTHON) -m pytest

SRCS := src/main.c src/topo.c src/alloc.c src/kernel.c
HDRS := src/fs_stride.h
BIN := fs_stride

.PHONY: help all build lint test test-asm test-sim smoke sweep repro clean

help:
	@echo "Targets: build all smoke sweep test test-asm test-sim repro lint clean"

build: $(BIN)

$(BIN): $(SRCS) $(HDRS)
	$(CC) $(CFLAGS) $(SRCS) -o $(BIN) -lm

all: build sweep

lint:
	$(CC) $(CFLAGS) $(SRCS) -o /tmp/fs_stride_gcc_lint -lm && rm -f /tmp/fs_stride_gcc_lint
	@if command -v clang >/dev/null 2>&1; then \
		clang $(CFLAGS) $(SRCS) -o /tmp/fs_stride_clang_lint -lm && rm -f /tmp/fs_stride_clang_lint; \
	elif [ "$${REQUIRE_CLANG:-0}" = "1" ]; then \
		echo "clang missing and REQUIRE_CLANG=1" >&2; exit 1; \
	else \
		echo "clang not installed; skipped clang -Werror check"; \
	fi
	@if command -v ruff >/dev/null 2>&1 || $(PYTHON) -m ruff --version >/dev/null 2>&1; then \
		$(PYTHON) -m ruff check analysis/ tests/ && $(PYTHON) -m ruff format --check analysis/ tests/; \
	fi
	@if command -v shellcheck >/dev/null 2>&1; then \
		shellcheck scripts/*.sh tests/unit/*.sh tests/integration/*.sh; \
	fi

test: build
	$(CC) $(SAN_CFLAGS) tests/unit/test_alloc.c src/alloc.c -Isrc -o /tmp/test_alloc -lm && /tmp/test_alloc && rm -f /tmp/test_alloc
	$(CC) $(SAN_CFLAGS) tests/unit/test_layout.c src/alloc.c src/kernel.c src/topo.c -Isrc -o /tmp/test_layout -lm && /tmp/test_layout && rm -f /tmp/test_layout
	$(CC) $(SAN_CFLAGS) $(SRCS) -o /tmp/fs_stride_san -lm && \
		FS_STRIDE_BIN=/tmp/fs_stride_san bash tests/unit/test_topo.sh && \
		FS_STRIDE_BIN=/tmp/fs_stride_san bash tests/unit/test_schedule.sh && \
		FS_STRIDE_BIN=/tmp/fs_stride_san bash tests/unit/test_kernel.sh && \
		rm -f /tmp/fs_stride_san
	FS_STRIDE_BIN=$(CURDIR)/$(BIN) bash tests/integration/nt05.sh
	@if ls tests/unit/test_*.py >/dev/null 2>&1; then \
		PYTHONPATH=analysis $(PYTEST) tests/unit/; \
	fi

test-asm: build
	bash tests/unit/test_asm.sh ./$(BIN)

test-sim:
	PYTHONPATH=analysis $(PYTHON) -m fs_stride_analysis.cli sim

smoke: build
	bash tests/integration/smoke.sh

sweep: build
	bash scripts/run_all.sh

repro: build
	bash tests/integration/repro.sh

clean:
	rm -f $(BIN) /tmp/fs_stride_* /tmp/test_alloc /tmp/test_layout
	rm -rf results/* analysis/*.egg-info analysis/__pycache__ analysis/fs_stride_analysis/__pycache__ tests/**/__pycache__ .pytest_cache
