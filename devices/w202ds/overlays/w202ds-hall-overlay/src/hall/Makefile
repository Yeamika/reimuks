# SPDX-License-Identifier: GPL-2.0-only
CROSS_COMPILE ?= aarch64-linux-gnu-
CC = $(CROSS_COMPILE)gcc
PYTHON ?= python3
REPO := $(abspath ../../../../../../)
OUT ?= $(shell $(PYTHON) "$(REPO)/scripts/output_paths.py" --board w202ds)/server-hall
CPPFLAGS ?=
CFLAGS ?= -std=c11 -O2 -Wall -Wextra -Werror
LDFLAGS ?=
.PHONY: all stage
all: $(OUT)/w202-server-hall
$(OUT)/w202-server-hall: hall.c
	mkdir -p "$(OUT)"
	$(CC) $(CPPFLAGS) $(CFLAGS) $< $(LDFLAGS) -o "$@.new"
	mv "$@.new" "$@"
stage: all
	install -D -m 0755 "$(OUT)/w202-server-hall" "$(OUT)/rootfs/usr/libexec/w202-server-hall"
