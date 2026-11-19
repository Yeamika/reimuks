# SPDX-License-Identifier: GPL-2.0-only
CC ?= cc
REPO := $(abspath ../../../../../../)
PYTHON ?= python3
BOARD ?= $(REPO)/devices/w202ds
NATIVE_HEADER := $(shell $(PYTHON) "$(REPO)/scripts/board_exports.py" --board "$(BOARD)" --export native-header)
NATIVE_INCLUDE := $(dir $(NATIVE_HEADER))
OUT ?= $(shell $(PYTHON) "$(REPO)/scripts/output_paths.py" --board w202ds)/device-controls
CPPFLAGS += -I$(NATIVE_INCLUDE) -Isource
CFLAGS ?= -std=gnu11 -Os -Wall -Wextra -Werror -Wno-unused-function -Wno-misleading-indentation
PROGRAMS := w202-usb-settings w202-device-controls w202-gnss-control w202-bluetooth-state w202-tablet-resync w202-hotspot-switch w202-hotspot-scan w202-wifi-recover
.PHONY: all stage
all: $(addprefix $(OUT)/bin/,$(PROGRAMS))
$(OUT)/bin:
	mkdir -p "$@"
$(OUT)/bin/w202-device-controls: source/controls.c source/network.c source/controls.h source/bus.h $(NATIVE_HEADER) | $(OUT)/bin
	$(CC) $(CPPFLAGS) $(CFLAGS) source/controls.c source/network.c $(LDFLAGS) -o "$@"
$(OUT)/bin/w202-gnss-control: source/gnss-control.c $(NATIVE_HEADER) | $(OUT)/bin
	$(CC) $(CPPFLAGS) $(CFLAGS) $< $(LDFLAGS) -o "$@"
$(OUT)/bin/w202-tablet-resync: source/tablet-resync.c $(NATIVE_HEADER) | $(OUT)/bin
	$(CC) $(CPPFLAGS) $(CFLAGS) $< $(LDFLAGS) -o "$@"
$(OUT)/bin/w202-bluetooth-state: source/bluetooth-state.c source/bluetooth-radio.h source/bus.h source/signals.h $(NATIVE_HEADER) | $(OUT)/bin
	$(CC) $(CPPFLAGS) $(CFLAGS) $< $(LDFLAGS) -l:libsystemd.so.0 -o "$@"
stage: all
	install -d "$(OUT)/rootfs/usr/libexec"
	for p in $(PROGRAMS); do install -m 0755 "$(OUT)/bin/$$p" "$(OUT)/rootfs/usr/libexec/$$p"; done

$(OUT)/bin/w202-hotspot-switch: source/hotspot.c source/bus.h $(NATIVE_HEADER) | $(OUT)/bin
	$(CC) $(CPPFLAGS) $(CFLAGS) $< $(LDFLAGS) -o "$@"
$(OUT)/bin/w202-hotspot-scan: source/hotspot-scan.c $(NATIVE_HEADER) | $(OUT)/bin
	$(CC) $(CPPFLAGS) $(CFLAGS) $< $(LDFLAGS) -o "$@"
$(OUT)/bin/w202-wifi-recover: source/wifi-recover.c source/bus.h $(NATIVE_HEADER) | $(OUT)/bin
	$(CC) $(CPPFLAGS) $(CFLAGS) $< $(LDFLAGS) -o "$@"
$(addprefix $(OUT)/bin/,$(PROGRAMS)): $(NATIVE_HEADER)

$(OUT)/bin/w202-usb-settings: source/usb-settings.c $(NATIVE_HEADER) | $(OUT)/bin
	$(CC) $(CPPFLAGS) $(CFLAGS) $< $(LDFLAGS) -o "$@"
