# SPDX-License-Identifier: GPL-2.0-only
# Optional console policy helper; not installed or enabled by default.
CROSS_COMPILE ?= aarch64-linux-gnu-
CC = $(CROSS_COMPILE)gcc
PYTHON ?= python3
REPO := $(abspath ../../../../../../)
OUT ?= $(shell $(PYTHON) "$(REPO)/scripts/output_paths.py" --board w202ds)/userspace/display
CPPFLAGS ?=
CFLAGS ?= -std=gnu11 -O2 -Wall -Wextra -Werror
LDFLAGS ?= -static
.PHONY: all install
all: $(OUT)/w202-screen
$(OUT)/w202-screen: source/w202-screen.c
	mkdir -p "$(OUT)"
	$(CC) $(CPPFLAGS) $(CFLAGS) $< $(LDFLAGS) -o "$@"
install: all
	test -n "$(DESTDIR)" && test "$(DESTDIR)" != /
	install -D -m 0755 "$(OUT)/w202-screen" "$(DESTDIR)/usr/libexec/w202-screen"
