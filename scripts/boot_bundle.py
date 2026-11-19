#!/usr/bin/env python3
"""Assemble inputs for the W202DS LinuxBoot loader; does not flash anything."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import zlib


def boot_options(options, kernel_config=None):
    """Preserve Kbuild defaults when nonempty EFI options replace them.

    ARM64 CMDLINE_FROM_BOOTLOADER selects the complete firmware command line;
    appending only systemd.unit would otherwise discard console/clock policy.
    CMDLINE_EXTEND already performs this merge inside the kernel.
    """
    if kernel_config is not None:
        values = dict(line.split('=', 1) for line in kernel_config.read_text().splitlines()
                      if line.startswith('CONFIG_') and '=' in line)
        if options and values.get('CONFIG_CMDLINE_FORCE') == 'y':
            raise ValueError('CONFIG_CMDLINE_FORCE prevents EFI boot options')
        if values.get('CONFIG_CMDLINE_EXTEND') != 'y':
            defaults = json.loads(values.get('CONFIG_CMDLINE', '""'))
            if not isinstance(defaults, str):
                raise ValueError('invalid CONFIG_CMDLINE')
            options = ' '.join(value for value in (defaults, options) if value)
    if len(options) >= 1024 or any(ord(c) < 32 or ord(c) > 126 for c in options):
        raise ValueError('options must be a single ASCII line shorter than 1024 bytes')
    return options


def assemble(image, initrd, dtb, partuuid):
    if not re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', partuuid):
        raise ValueError('root PARTUUID must be a canonical GPT UUID')
    if len(image) < 64 or image[56:60] != b'ARM\x64':
        raise ValueError('not an ARM64 Linux Image')
    offset, memory, flags = struct.unpack_from('<QQQ', image, 8)
    if flags != 10 or offset >= 0x200000 or memory < len(image) or memory > 0x4000000-offset:
        raise ValueError('Image does not match the current LinuxBoot memory contract')
    if not 0 < len(initrd) <= 0x4000000 or initrd[:4] != b'\x02\x21\x4c\x18':
        raise ValueError('expected a nonempty legacy LZ4 initramfs, at most 64 MiB')
    if not 40 <= len(dtb) <= 0x100000 or dtb[:4] != b'\xd0\x0d\xfe\xed':
        raise ValueError('expected a DTB, at most 1 MiB')
    if struct.unpack_from('>I', dtb, 4)[0] > len(dtb):
        raise ValueError('truncated DTB')
    header = bytearray(4096)
    header[:8] = b'ANDROID!'
    struct.pack_into('<III', header, 8, len(image), len(initrd), 0)
    struct.pack_into('<I', header, 20, 1584)
    struct.pack_into('<I', header, 40, 4)
    boot = bytes(header) + image + bytes((-len(image)) % 4096) + initrd
    meta = b'W202LX01' + struct.pack('<6I', len(image), len(initrd), len(dtb),
                                       zlib.crc32(image), zlib.crc32(initrd), zlib.crc32(dtb))
    return boot, meta


def main():
    p = argparse.ArgumentParser(description=__doc__)
    entries = {'server': 'DebianServer', 'kde': 'DebianKDE', 'gnome': 'DebianGNOME'}
    p.add_argument('--profile', choices=entries, required=True)
    for name in ('image', 'initrd', 'dtb', 'output'):
        p.add_argument('--'+name, type=Path, required=True)
    p.add_argument('--root-partuuid', required=True)
    p.add_argument('--options', default='', help='kernel boot options, including systemd.unit if required')
    p.add_argument('--kernel-config', type=Path,
                   help='matching kernel .config; retain its default command line before EFI options')
    p.add_argument('--legacy', action='store_true', help='emit the combined boot.img format for old EFI loaders')
    a = p.parse_args()
    try:
        a.options = boot_options(a.options, a.kernel_config)
    except (OSError, ValueError) as error:
        p.error(str(error))
    image, initrd, dtb = (f.read_bytes() for f in (a.image, a.initrd, a.dtb))
    boot, meta = assemble(image, initrd, dtb, a.root_partuuid)
    # One output directory per profile avoids silently mixing shared DTBs.
    a.output = a.output.resolve()
    if any(a.output == path.resolve() or a.output in path.resolve().parents
           for path in (a.image, a.initrd, a.dtb)):
        p.error('output must be separate from payload inputs')
    receipt = a.output/'manifest.json'
    if a.output.exists():
        if not receipt.is_file():
            p.error('refusing to replace an unrecognized output directory')
        previous = json.loads(receipt.read_text())
        if previous.get('profile') != a.profile or 'files' not in previous:
            p.error('existing output belongs to another profile')
        for name in previous['files']:
            target = a.output/name
            if not target.resolve().is_relative_to(a.output):
                p.error('invalid previous artifact path')
        for name in previous['files']:
            (a.output/name).unlink(missing_ok=True)
    a.output.mkdir(parents=True, exist_ok=True)
    profile = a.output/'EFI'/entries[a.profile]
    profile.mkdir(parents=True, exist_ok=True)
    common = a.output/'EFI'/'W202DS'
    common.mkdir(exist_ok=True)
    if a.legacy:
        outputs = {profile/'boot.img': boot, profile/'payload.bin': meta,
                   profile/'root-partuuid': a.root_partuuid.encode('ascii'), common/'LINUX.DTB': dtb}
    else:
        prefix = '/'+str(profile.relative_to(a.output)).replace('\\', '/')
        config = (f'kernel={prefix}/Image\ninitramfs={prefix}/initramfs.cpio.lz4\n'
                  f'dtb={prefix}/board.dtb\nmetadata={prefix}/payload.bin\n'
                  f'root-partuuid={a.root_partuuid}\noptions={a.options}\n')
        outputs = {profile/'Image': image, profile/'initramfs.cpio.lz4': initrd,
                   profile/'board.dtb': dtb, profile/'payload.bin': meta,
                   profile/'linuxboot.conf': config.encode('ascii')}
    for path, data in outputs.items():
        path.write_bytes(data)
    (a.output/'manifest.json').write_text(json.dumps({
        'profile': a.profile, 'root_partuuid': a.root_partuuid,
        'files': {str(path.relative_to(a.output)): hashlib.sha256(data).hexdigest()
                  for path, data in outputs.items()},
        'format': 'legacy' if a.legacy else 'linuxboot.conf',
        'kernel_options': a.options,
        'note': 'Payload only; requires matching separately built LinuxBoot EFI. CRC is not authentication.'
    }, indent=2)+'\n')


if __name__ == '__main__':
    main()
