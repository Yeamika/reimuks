#!/bin/sh
set -eu
cd -- "$(dirname -- "$0")"
shared=../../../rootfs/desktop-common
repo=../../../../..
native="$repo/build/device-controls"
test "$(id -u)" = 0
test -x /usr/libexec/w202ds-gnss
command -v kdialog >/dev/null
command -v pkexec >/dev/null
install -D -m 0755 "$native/rootfs/usr/libexec/w202-gnss-control" /usr/libexec/w202-gnss-control
install -D -m 0755 "$native/kde-rootfs/usr/libexec/w202-gnss-toggle" /usr/libexec/w202-gnss-toggle
install -D -m 0644 "$shared/usr/lib/systemd/system/w202-gnss.service" /usr/lib/systemd/system/w202-gnss.service
install -D -m 0644 "$shared/usr/share/polkit-1/actions/org.reimuks.gnss.policy" /usr/share/polkit-1/actions/org.reimuks.gnss.policy
install -D -m 0644 w202-gnss.desktop /usr/share/applications/w202-gnss.desktop
systemctl daemon-reload
