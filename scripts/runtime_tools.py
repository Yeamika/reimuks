#!/usr/bin/env python3
"""Prepare minimal initramfs tools without constructing a Server rootfs."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess

import build as backend


def prepare():
    description = json.loads((backend.REPO/'config/initramfs-tools.json').read_text())
    required = set(description['packages'])
    candidates = {}
    for state in sorted(backend.package_cache('').glob('apt-*')):
        for (name, arch), (version, archive) in backend.cached_packages(state).items():
            if name not in required or arch not in (backend.DISTRIBUTION['architecture'], 'all'):
                continue
            previous = candidates.get(name)
            if previous is None or subprocess.run(['dpkg', '--compare-versions', version, 'gt', previous[0]]).returncode == 0:
                candidates[name] = (version, archive)
    if required - candidates.keys():
        state = backend.apt_state('apt-initramfs', backend.DISTRIBUTION['architecture'])
        backend.apt(state, 'update')
        backend.apt(state, '--download-only', '--no-install-recommends', '-y', 'install', *sorted(required))
        for (name, arch), candidate in backend.cached_packages(state).items():
            if name in required and arch in (backend.DISTRIBUTION['architecture'], 'all'):
                candidates[name] = candidate
    if required - candidates.keys():
        raise ValueError('Missing initramfs tool packages')
    output = backend.board_build()/'initramfs-tools'
    hashes = {name: {'version': version, 'sha256': backend.digest(archive)}
              for name, (version, archive) in candidates.items()}
    marker = output/'manifest.json'
    if marker.exists() and json.loads(marker.read_text()) == hashes:
        return output/'root'
    root = output/'root'
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    for version, archive in candidates.values():
        backend.run(['dpkg-deb', '-x', archive, root])
    backend.write(marker, json.dumps(hashes, indent=2)+'\n')
    return root


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--board', required=True)
    args = parser.parse_args()
    backend.select_board(args.board)
    print(prepare())
