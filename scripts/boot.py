#!/usr/bin/env python3
"""Select a board and delegate boot firmware compilation to its board project."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]


def boards():
    result = {}
    for file in sorted((REPO/'devices').glob('*/board.json')):
        config = json.loads(file.read_text())
        if config.get('schema') != 1 or config.get('board') != file.parent.name:
            raise ValueError(f'invalid board description: {file}')
        result[file.parent.name] = (file.parent, config)
    return result


def main():
    registry = boards()
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['list', 'build'])
    p.add_argument('--board', choices=sorted(registry))
    p.add_argument('--stage', choices=['all', 'uefi', 'efi'], default='all')
    p.add_argument('--output', type=Path)
    p.add_argument('--source-cache', type=Path)
    p.add_argument('--jobs', type=int, default=4)
    a = p.parse_args()
    if a.action == 'list':
        for name, (_, config) in registry.items():
            print(f'{name}: {config["architecture"]}; profiles: {", ".join(config["profiles"])}')
        return
    if not a.board or not a.output or a.jobs < 1:
        p.error('build requires --board, --output and positive --jobs')
    directory, config = registry[a.board]
    builder = (directory/config['boot_builder']).resolve()
    boot = (directory/'boot').resolve()
    if boot not in builder.parents or not builder.is_file():
        p.error('board boot builder must exist inside the linked boot project')
    argv = [sys.executable, str(builder), '--output', str(a.output.resolve()),
            '--stage', a.stage, '--jobs', str(a.jobs), '--kernel-source', str((directory/'kernel').resolve())]
    if a.source_cache:
        argv += ['--source-cache', str(a.source_cache.resolve())]
    subprocess.run(argv, check=True)


if __name__ == '__main__':
    main()
