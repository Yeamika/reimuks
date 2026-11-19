#!/usr/bin/env python3
"""Add separately packaged server services to the cached Debian offline adapter."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys

LAYER = Path(__file__).resolve().parent
sys.path.insert(0, str(LAYER.parents[3]/'scripts'))
from compose_target import existing_file
from debian_overlay import adapt, record_deb, reuse_package, shared_powerkey
from output_paths import shared_root
from overlay_package import staging


def replace_records(records, added, field):
    replaced = {r[field] for r in added}
    result = []
    for record in records:
        if record['package'] == 'reimuks-desktop-server-common':
            result.extend(added)
        elif record[field] not in replaced:
            result.append(record)
    return result


def package(pool, archive, output, architecture, mode):
    files = lambda prefix, layer: pool/prefix/architecture/layer/'package.json'
    common = files('overlays/services', 'server-common')
    hardware = files('overlays/w202ds', 'powerkey-interface')
    power = files('overlays/services', 'powerkey')
    receipt = json.loads((archive/'package.json').read_text())
    board_manifest = f'board-debian-{mode}.json'
    deps_manifest = f'board-debian-{mode}.deps.json'
    board = json.loads((archive/board_manifest).read_text())
    deps = json.loads((archive/deps_manifest).read_text())
    with staging(output) as (_, export):
        items = [shared_powerkey(power, export, architecture),
                 adapt(hardware, export, name='reimuks-w202ds-powerkey-interface',
                       kind='powerkey-interface', architecture=architecture,
                       depends=['reimuks-w202ds-kernel-runtime'],
                       provides=['reimuks-powerkey-interface']),
                 adapt(common, export, name='reimuks-desktop-server-common',
                       kind='server-common', architecture=architecture, version_base='1.1',
                       depends=['systemd', 'reimuks-powerkey', 'reimuks-powerkey-interface'],
                       conflicts=['reimuks-w202ds-server', 'reimuks-w202ds-kde', 'reimuks-w202ds-gnome'],
                       replaces=['reimuks-w202ds-server'],
                       postinst='rm -f -- /etc/systemd/system/multi-user.target.wants/systemd-networkd.service')]
        records = {item['file']: item['sha256'] for item in items}
        for name in receipt['files']:
            if name not in {*records, board_manifest, deps_manifest}:
                reuse_package(existing_file(archive.resolve(), name), export/name)
                records[name] = receipt['files'][name]
        board['packages'] = replace_records(board['packages'], items, 'file')
        deps['packages'] = replace_records(deps['packages'],
                                          [record_deb(export, item['file']) for item in items],
                                          'file')
        for name, data in [(board_manifest, board), (deps_manifest, deps)]:
            path = export/name
            path.write_text(json.dumps(data, indent=2)+'\n')
            records[name] = sha256(path.read_bytes()).hexdigest()
        requires = [item for item in receipt['requires']
                    if item not in ('powerkey', 'powerkey-interface')]
        i = requires.index('server-common')
        requires[i:i] = ['powerkey', 'powerkey-interface']
        receipt.update(requires=requires, files=records)
        (export/'package.json').write_text(json.dumps(receipt, indent=2, sort_keys=True)+'\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--architecture', required=True, choices=['arm64'])
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--seed', type=Path, help='Previously verified offline dependency bundle')
    args = parser.parse_args()
    mode = args.output.name
    if mode not in ('server', 'server2'):
        parser.error('output directory must be named server or server2')
    os.umask(0o022)
    pool = Path(os.environ.get('REIMUKS_PACKAGE_ROOT', shared_root()/'packages'))
    seed = args.seed or shared_root()/'adapter-inputs/w202ds/debian/trixie'/args.architecture/mode
    try:
        package(pool, seed, args.output, args.architecture, mode)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'{parser.prog}: {error}\n')


if __name__ == '__main__':
    main()
