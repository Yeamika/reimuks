#!/bin/sh
# Install verified archives into an already mounted, empty offline filesystem.
# Partition creation/formatting and firmware flashing are separate operations.
set -eu
if [ "$#" -ne 5 ]; then
    echo 'Usage: install-rootfs.sh TARGET ROOTFS ROOTFS_SHA256 KERNEL_RUNTIME RUNTIME_SHA256' >&2
    exit 2
fi
target=$1
rootfs=$2
rootfs_sha=$3
runtime=$4
runtime_sha=$5
test "$(id -u)" = 0 || { echo 'Root is required' >&2; exit 1; }
test -d "$target" && test ! -L "$target"
target=$(cd "$target" && pwd -P)
test "$target" != / && test "$target" != /usr && test "$target" != /home
test ! -e "$target/etc" && test ! -e "$target/usr" || {
    echo 'Target must be an empty offline filesystem' >&2; exit 1;
}
printf '%s  %s\n' "$rootfs_sha" "$rootfs" | sha256sum -c -
printf '%s  %s\n' "$runtime_sha" "$runtime" | sha256sum -c -
tar -xpf "$rootfs" -C "$target"
tar -xpf "$runtime" -C "$target"
(
    cd "$target"
    sha256sum -c usr/lib/reimuks/kernel-files.sha256
)
release=$(cat "$target/usr/lib/reimuks/kernel-release")
test -n "$release"
chroot "$target" /usr/sbin/depmod -a "$release"
test -s "$target/usr/lib/modules/$release/modules.dep"
# Re-run the packaged userspace contract natively in the installed tree.
# No hardware helper is executed by this contract.
chroot "$target" /usr/bin/python3 -c '
import json, subprocess
with open("/usr/lib/reimuks/startup-preflight.json") as stream:
    report = json.load(stream)
assert report["schema"] == 1 and report["method"] == "target-userspace"
for command in report["commands"]:
    subprocess.run(command, check=True, timeout=120)
'
sync
echo "Installed rootfs and matched kernel runtime: $release"
