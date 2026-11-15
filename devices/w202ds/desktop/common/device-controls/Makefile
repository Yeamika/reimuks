# SPDX-License-Identifier: GPL-2.0-only
CC ?= cc
REPO := $(abspath ../../../../..)
PYTHON ?= python3
BOARD ?= $(REPO)/devices/w202ds
NATIVE_HEADER := $(shell $(PYTHON) "$(REPO)/scripts/board_exports.py" --board "$(BOARD)" --export native-header)
NATIVE_INCLUDE := $(dir $(NATIVE_HEADER))
OUT ?= $(REPO)/build/device-controls
CPPFLAGS += -I$(NATIVE_INCLUDE) -Isource
CFLAGS ?= -std=gnu11 -Os -Wall -Wextra -Werror -Wno-unused-function -Wno-misleading-indentation
KDE := $(REPO)/devices/w202ds/desktop/kde/session
PROGRAMS := w202-usb-settings w202-device-controls w202-gnss-control w202-bluetooth-state w202-tablet-resync w202-hardware-controls w202-tablet-mode w202-lid-wake w202-tablet-notify w202-hotspot-switch w202-hotspot-scan w202-gnss-toggle
.PHONY: all stage hardware
all: $(addprefix $(OUT)/bin/,$(PROGRAMS))
$(OUT)/bin:
	mkdir -p "$@"
$(OUT)/bin/w202-device-controls: source/controls.c source/network.c source/controls.h source/bus.h $(NATIVE_HEADER) | $(OUT)/bin
	$(CC) $(CPPFLAGS) $(CFLAGS) source/controls.c source/network.c $(LDFLAGS) -o "$@"
$(OUT)/bin/w202-gnss-control: source/gnss-control.c $(NATIVE_HEADER) | $(OUT)/bin
	$(CC) $(CPPFLAGS) $(CFLAGS) $< $(LDFLAGS) -o "$@"
$(OUT)/bin/w202-tablet-resync: source/tablet-resync.c $(NATIVE_HEADER) | $(OUT)/bin
	$(CC) $(CPPFLAGS) $(CFLAGS) $< $(LDFLAGS) -o "$@"
$(OUT)/bin/w202-bluetooth-state: source/bluetooth-state.c source/bus.h source/signals.h $(NATIVE_HEADER) | $(OUT)/bin
	$(CC) $(CPPFLAGS) $(CFLAGS) $< $(LDFLAGS) -l:libsystemd.so.0 -o "$@"
$(OUT)/bin/w202-hardware-controls: $(KDE)/hardware-controls.c source/bus.h | $(OUT)/bin
	$(CC) $(CPPFLAGS) $(CFLAGS) $< $(LDFLAGS) -o "$@"
$(OUT)/bin/w202-tablet-mode: $(KDE)/tablet-mode.c source/bus.h | $(OUT)/bin
	$(CC) $(CPPFLAGS) $(CFLAGS) $< $(LDFLAGS) -o "$@"
$(OUT)/bin/w202-lid-wake: $(KDE)/lid-wake.c source/bus.h source/signals.h | $(OUT)/bin
	$(CC) $(CPPFLAGS) $(CFLAGS) $< $(LDFLAGS) -l:libsystemd.so.0 -o "$@"
$(OUT)/bin/w202-tablet-notify: $(KDE)/tablet-notify.c source/bus.h source/signals.h | $(OUT)/bin
	$(CC) $(CPPFLAGS) $(CFLAGS) $< $(LDFLAGS) -l:libsystemd.so.0 -o "$@"
# Hardware outputs remain owned by their hardware component, not this layer.
hardware:
	$(PYTHON) "$(REPO)/scripts/board-build.py" --board "$(BOARD)" --cc "$(CC)"
stage: all
	install -d "$(OUT)/rootfs/usr/libexec" "$(OUT)/kde-rootfs/usr/libexec"
	for p in w202-usb-settings w202-device-controls w202-gnss-control w202-bluetooth-state w202-tablet-resync w202-hotspot-switch w202-hotspot-scan; do install -m 0755 "$(OUT)/bin/$$p" "$(OUT)/rootfs/usr/libexec/$$p"; done
	for p in w202-hardware-controls w202-tablet-mode w202-lid-wake w202-tablet-notify w202-gnss-toggle; do install -m 0755 "$(OUT)/bin/$$p" "$(OUT)/kde-rootfs/usr/libexec/$$p"; done

$(OUT)/bin/w202-hotspot-switch: source/hotspot.c source/bus.h $(NATIVE_HEADER) | $(OUT)/bin
	$(CC) $(CPPFLAGS) $(CFLAGS) $< $(LDFLAGS) -o "$@"
$(OUT)/bin/w202-hotspot-scan: source/hotspot-scan.c $(NATIVE_HEADER) | $(OUT)/bin
	$(CC) $(CPPFLAGS) $(CFLAGS) $< $(LDFLAGS) -o "$@"
$(OUT)/bin/w202-gnss-toggle: $(KDE)/gnss-toggle.c $(NATIVE_HEADER) | $(OUT)/bin
	$(CC) $(CPPFLAGS) $(CFLAGS) $< $(LDFLAGS) -o "$@"

$(addprefix $(OUT)/bin/,$(PROGRAMS)): $(NATIVE_HEADER)

$(OUT)/bin/w202-usb-settings: source/usb-settings.c $(NATIVE_HEADER) | $(OUT)/bin
	$(CC) $(CPPFLAGS) $(CFLAGS) $< $(LDFLAGS) -o "$@"
