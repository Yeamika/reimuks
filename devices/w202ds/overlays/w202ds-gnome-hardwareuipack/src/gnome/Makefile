# SPDX-License-Identifier: GPL-2.0-only
CC ?= cc
REPO := $(abspath ../../../../../../)
PYTHON ?= python3
BOARD ?= $(REPO)/devices/w202ds
NATIVE_HEADER := $(shell $(PYTHON) "$(REPO)/scripts/board_exports.py" --board "$(BOARD)" --export native-header)
COMMON := ../../../w202ds-hardwarepack2/src/device-controls/source
OUT ?= $(shell $(PYTHON) "$(REPO)/scripts/output_paths.py" --board w202ds)/desktop-gnome
CPPFLAGS += -I$(dir $(NATIVE_HEADER)) -I$(COMMON)
CFLAGS ?= -std=gnu11 -Os -Wall -Wextra -Werror -Wno-unused-function -Wno-misleading-indentation
.PHONY: all stage
all: $(OUT)/bin/w202-gnome-controls
$(OUT)/bin:
	mkdir -p "$@"
$(OUT)/bin/w202-gnome-controls: session/controls.c $(COMMON)/session.h $(COMMON)/bus.h $(NATIVE_HEADER) | $(OUT)/bin
	$(CC) $(CPPFLAGS) $(CFLAGS) $< $(LDFLAGS) -o "$@"
stage: all
	install -D -m 0755 "$(OUT)/bin/w202-gnome-controls" "$(OUT)/rootfs/usr/libexec/w202-gnome-controls"
