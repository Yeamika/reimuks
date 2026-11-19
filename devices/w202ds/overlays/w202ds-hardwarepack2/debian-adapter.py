#!/usr/bin/env python3
"""Bundle W202DS hardware packages shared by Debian desktops."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

LAYER = Path(__file__).resolve().parent
sys.path.insert(0, str(LAYER.parents[3]/'scripts'))
from build import digest
from compose_target import existing_file, package
from debian_overlay import adapt, reuse_package
from distributions import DEFAULT, load_distribution
from output_paths import shared_root
from overlay_package import staging


BOARD = 'w202ds'
PACK2 = 'reimuks-w202ds-hardwarepack2'
KERNEL_RUNTIME = 'reimuks-w202ds-kernel-runtime'


def bundle(pool, seed, output, distribution, architecture):
    target = dict(board=BOARD, architecture=architecture, distribution=distribution)
    data, source = package(existing_file(seed.resolve(), 'package.json'), target, {})
    if data['id'] != 'w202ds-hardware-inputs' or data.get('private'):
        raise ValueError('Expected verified common W202DS hardware inputs')
    receipt = existing_file(pool.resolve(), f'overlays/{BOARD}/{architecture}/hardwarepack2/package.json')
    with staging(output) as (_, export):
        records = {}
        for name, path in source.items():
            if not name.endswith('.deb') or digest(path) != data['files'][name]:
                raise ValueError(f'Invalid cached hardware input: {name}')
            reuse_package(path, export/name)
            records[name] = data['files'][name]
        if KERNEL_RUNTIME+'.deb' not in records or PACK2+'.deb' in records:
            raise ValueError('Expected the shared kernel runtime and separate Pack2 sources')
        pack2 = adapt(receipt, export, name=PACK2, kind='hardwarepack2', architecture=architecture,
                      depends=[KERNEL_RUNTIME, 'pkexec', 'upower'])
        records[pack2['file']] = pack2['sha256']
        (export/'package.json').write_text(json.dumps(dict(
            schema=1, id='debian-hardware-adapter', **target,
            requires=['kernel', 'distribution', 'hardwarepack2'], files=records), indent=2)+'\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--distribution', default=os.environ.get('REIMUKS_DISTRIBUTION', DEFAULT))
    parser.add_argument('--architecture', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seed', type=Path, help='Verified cached W202DS hardware Debian packages')
    args = parser.parse_args()
    os.umask(0o022)
    try:
        if load_distribution(args.distribution)['architecture'] != args.architecture:
            raise ValueError('Distribution and hardware architecture differ')
        shared = shared_root()
        pool = Path(os.environ.get('REIMUKS_PACKAGE_ROOT', shared/'packages'))
        seed = args.seed or shared/'adapter-inputs'/BOARD/args.distribution/args.architecture/'hardware'
        bundle(pool, seed, args.output, args.distribution, args.architecture)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'{parser.prog}: {error}\n')


if __name__ == '__main__':
    main()
