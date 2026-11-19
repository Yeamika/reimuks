#!/usr/bin/env python3
"""Publish the already-built, matched Polaris kernel, DTB and modules."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys

LAYER = Path(__file__).resolve().parent
sys.path.insert(0, str(LAYER.parents[3]/'scripts'))
from overlay_package import portable, staging


def digest(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def package(runtime, output):
    identity = json.loads((runtime/'identity.json').read_text())
    release = identity['release']
    if identity['board'] != 'polaris' or not re.fullmatch(r'[\w.+-]+-polaris[\w.+-]*', release):
        raise ValueError('Expected a Polaris kernel identity')
    images = {'Image': 'image_sha256', 'config': 'config_sha256', 'polaris.dtb': 'dtb_sha256'}
    modules = runtime/'modules'/release
    if {str(path.relative_to(modules)): digest(path) for path in modules.rglob('*.ko')} != identity['module_hashes']:
        raise ValueError('Polaris module set differs from the exported identity')
    with staging(output) as (root, export):
        (root/'boot').mkdir()
        for name, key in images.items():
            path = runtime/name
            if digest(path) != identity[key]:
                raise ValueError(f'Polaris {name} differs from the exported identity')
            filename = f'polaris-{release}.dtb' if name.endswith('.dtb') else f'{name}-{release}'
            shutil.copyfile(path, root/'boot'/filename)
        shutil.copytree(modules, root/'usr/lib/modules'/release, symlinks=True)
        for link in ['build', 'source']:
            (root/'usr/lib/modules'/release/link).unlink(missing_ok=True)
        identity['after_install'] = ['depmod -a '+release]
        meta = export/'kernel.manifest.json'
        meta.write_text(json.dumps(identity, indent=2)+'\n')
        portable(root, export, 'kernel', 'kernel-polaris-arm64.tar.gz',
                 'arm64', [], board='polaris', metadata=[meta])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--architecture', required=True, choices=['arm64'])
    parser.add_argument('--runtime', type=Path, default=LAYER.parents[1]/'kernel/output/runtime-desktop')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    os.umask(0o022)
    try:
        package(args.runtime, args.output)
    except (OSError, ValueError) as error:
        parser.exit(1, f'{parser.prog}: {error}\n')


if __name__ == '__main__':
    main()
