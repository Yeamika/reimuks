# SPDX-License-Identifier: GPL-2.0-only
CC ?= cc
REPO := $(abspath ../../../../../../../../)
PYTHON ?= python3
BOARD ?= $(REPO)/devices/w202ds
NATIVE_HEADER := $(shell $(PYTHON) "$(REPO)/scripts/board_exports.py" --board "$(BOARD)" --export native-header)
COMMON := ../../../../w202ds-hardwarepack2/src/device-controls/source
OUT ?= $(shell $(PYTHON) "$(REPO)/scripts/output_paths.py" --board w202ds)/desktop-kde
CPPFLAGS += -I$(dir $(NATIVE_HEADER)) -I$(COMMON)
CFLAGS ?= -std=gnu11 -Os -Wall -Wextra -Werror -Wno-unused-function -Wno-misleading-indentation
PROGRAMS := w202-hardware-controls w202-tablet-mode w202-lid-wake w202-tablet-notify w202-gnss-toggle
.PHONY: all stage
all: $(addprefix $(OUT)/bin/,$(PROGRAMS))
$(OUT)/bin:
	mkdir -p "$@"
$(OUT)/bin/w202-hardware-controls: hardware-controls.c $(COMMON)/session.h $(COMMON)/bus.h $(NATIVE_HEADER) | $(OUT)/bin
	$(CC) $(CPPFLAGS) $(CFLAGS) $< $(LDFLAGS) -o "$@"
$(OUT)/bin/w202-tablet-mode: tablet-mode.c $(COMMON)/bus.h $(NATIVE_HEADER) | $(OUT)/bin
	$(CC) $(CPPFLAGS) $(CFLAGS) $< $(LDFLAGS) -o "$@"
$(OUT)/bin/w202-lid-wake: lid-wake.c $(COMMON)/bus.h $(COMMON)/signals.h $(NATIVE_HEADER) | $(OUT)/bin
	$(CC) $(CPPFLAGS) $(CFLAGS) $< $(LDFLAGS) -l:libsystemd.so.0 -o "$@"
$(OUT)/bin/w202-tablet-notify: tablet-notify.c $(COMMON)/bus.h $(COMMON)/signals.h $(NATIVE_HEADER) | $(OUT)/bin
	$(CC) $(CPPFLAGS) $(CFLAGS) $< $(LDFLAGS) -l:libsystemd.so.0 -o "$@"
$(OUT)/bin/w202-gnss-toggle: gnss-toggle.c $(NATIVE_HEADER) | $(OUT)/bin
	$(CC) $(CPPFLAGS) $(CFLAGS) $< $(LDFLAGS) -o "$@"
stage: all
	install -d "$(OUT)/rootfs/usr/libexec"
	for p in $(PROGRAMS); do install -m 0755 "$(OUT)/bin/$$p" "$(OUT)/rootfs/usr/libexec/$$p"; done
