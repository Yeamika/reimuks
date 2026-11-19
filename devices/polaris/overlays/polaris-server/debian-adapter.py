#!/usr/bin/env python3
"""Build the Debian offline adapter for the Polaris Server layers."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

LAYER = Path(__file__).resolve().parent
REPO = LAYER.parents[3]
sys.path.insert(0, str(REPO/'scripts'))
import build
from compose_target import existing_file
from debian_overlay import adapt, record_deb, reuse_package, shared_powerkey
from distributions import identity
from output_paths import shared_root
from overlay_package import staging


def baseline(pool, architecture):
    directory = pool/'distro/debian/trixie'/architecture
    receipt = json.loads((directory/'package.json').read_text())
    name, = receipt['files']
    with tarfile.open(existing_file(directory.resolve(), name), 'r:gz') as archive:
        member = next(m for m in archive if m.name.removeprefix('./') == 'var/lib/dpkg/status')
        status = archive.extractfile(member).read()
    return hashlib.sha256(status).hexdigest(), status.count(b'Status: install ok installed')


def package(pool, cache, output, architecture):
    files = lambda prefix, layer: pool/prefix/architecture/layer/'package.json'
    selected = json.loads((REPO/'config/boards/polaris/packages.json').read_text())
    archive_hashes = json.loads((cache/'fetch-complete.json').read_text())
    if (archive_hashes['board'] != 'polaris' or
            archive_hashes['distribution']['architecture'] != architecture):
        raise ValueError(f'Expected a Polaris Debian cache: {cache}')
    base_hash, base_packages = baseline(pool, architecture)
    with staging(output) as (_, export):
        board = selected['board']
        server = selected['profiles']['server']
        items = [shared_powerkey(files('overlays/services', 'powerkey'), export, architecture),
                 adapt(files('overlays/polaris', 'hardware'), export, name=board['package'],
                       depends=board['depends'], architecture=architecture,
                       kind='polaris-hardware', version_base='1.1',
                       provides=['reimuks-powerkey-interface']),
                 adapt(files('overlays/polaris', 'server'), export, name=server['package'],
                       depends=[*server['depends'], 'reimuks-powerkey'], architecture=architecture,
                       kind='polaris-server', version_base='1.1')]
        records = {item['file']: item['sha256'] for item in items}
        third_party = []
        need = {'busybox-static', 'firmware-qcom-soc', 'firmware-atheros'}
        for name, digest in sorted(archive_hashes['archives'].items()):
            if name.split('_', 1)[0] not in need:
                continue
            relative = f'resolved-dependencies/{name}'
            reuse_package(existing_file((cache/'archives').resolve(), name), export/relative)
            record = record_deb(export, relative)
            if record['sha256'] != digest or record['package'] not in need:
                raise ValueError(f'Unexpected Debian cache archive: {name}')
            need.remove(record['package'])
            records[relative] = digest
            third_party.append(record)
        if need:
            raise ValueError(f'Missing Polaris runtime dependencies: {", ".join(sorted(need))}')
        board_manifest = dict(schema=1, board='polaris', profile='server', mode='debian-server',
                              distribution=identity(build.board_distribution('debian/trixie')), packages=items,
                              private_configuration_included=False, kernel_included=False, runtime_artifacts=[])
        deps = dict(schema=1, profile='server', mode='debian-server', architecture=architecture,
                    distro='debian/trixie', distro_status_sha256=base_hash, baseline_installed_packages=base_packages,
                    packages=[record_deb(export, item['file']) for item in items],
                    compatibility=[], runtime_dependencies=third_party)
        for name, data in [('board-debian-server.json', board_manifest), ('board-debian-server.deps.json', deps)]:
            path = export/name
            path.write_text(json.dumps(data, indent=2)+'\n')
            records[name] = build.digest(path)
        receipt = dict(schema=1, id='polaris-debian-server-adapter', board='polaris', architecture=architecture,
                       distribution='debian/trixie', requires=['kernel', 'distribution', 'powerkey',
                                                               'polaris-hardware', 'polaris-server'], files=records)
        (export/'package.json').write_text(json.dumps(receipt, indent=2, sort_keys=True)+'\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--architecture', required=True, choices=['arm64'])
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--apt-cache', type=Path)
    args = parser.parse_args()
    os.umask(0o022)
    build.select_board('polaris')
    pool = Path(os.environ.get('REIMUKS_PACKAGE_ROOT', shared_root()/'packages'))
    relative = Path('distributions/debian/trixie')/args.architecture/'cache/boards/polaris/apt-board-server'
    cache = args.apt_cache or shared_root()/relative
    if not args.apt_cache and not (cache/'fetch-complete.json').is_file():
        cache = REPO.parent/'POLARIS-DEV/build/reimuks/shared'/relative
    try:
        package(pool, cache, args.output, args.architecture)
    except (OSError, ValueError, StopIteration, subprocess.CalledProcessError) as error:
        parser.exit(1, f'{parser.prog}: {error}\n')


if __name__ == '__main__':
    main()
