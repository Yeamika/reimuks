#!/usr/bin/env python3
"""Assemble inputs for the W202DS LinuxBoot loader; does not flash anything."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import zlib


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
    p.add_argument('--profile', choices=['server', 'kde'], required=True)
    for name in ('image', 'initrd', 'dtb', 'output'):
        p.add_argument('--'+name, type=Path, required=True)
    p.add_argument('--root-partuuid', required=True)
    a = p.parse_args()
    image, initrd, dtb = (f.read_bytes() for f in (a.image, a.initrd, a.dtb))
    boot, meta = assemble(image, initrd, dtb, a.root_partuuid)
    # One output directory per profile avoids silently mixing shared DTBs.
    a.output.mkdir(parents=True, exist_ok=False)
    profile = a.output/'EFI'/('DebianServer' if a.profile == 'server' else 'DebianKDE')
    profile.mkdir(parents=True)
    common = a.output/'EFI'/'W202DS'
    common.mkdir()
    outputs = {profile/'boot.img': boot, profile/'payload.bin': meta,
               profile/'root-partuuid': a.root_partuuid.encode('ascii'), common/'LINUX.DTB': dtb}
    for path, data in outputs.items():
        path.write_bytes(data)
    (a.output/'manifest.json').write_text(json.dumps({
        'profile': a.profile, 'root_partuuid': a.root_partuuid,
        'files': {str(path.relative_to(a.output)): hashlib.sha256(data).hexdigest()
                  for path, data in outputs.items()},
        'note': 'Payload only; requires matching separately built LinuxBoot EFI. CRC is not authentication.'
    }, indent=2)+'\n')


if __name__ == '__main__':
    main()
