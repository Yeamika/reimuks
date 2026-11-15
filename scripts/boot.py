#!/usr/bin/env python3
"""Select a board and delegate boot firmware compilation to its board project."""
import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from verify_boot import verify

REPO = Path(__file__).resolve().parents[1]


def boards():
    result = {}
    for file in sorted((REPO/'devices').glob('*/board.json')):
        config = json.loads(file.read_text())
        if config.get('schema') != 1 or config.get('board') != file.parent.name:
            raise ValueError(f'invalid board description: {file}')
        result[file.parent.name] = (file.parent, config)
    return result


def publish(work, output):
    """Replace this stage's artifacts while retaining the other stage's identity."""
    verify(work, 'firmware-manifest.json')
    current = json.loads((work/'firmware-manifest.json').read_text())
    receipt = output/'firmware-manifest.json'
    previous = json.loads(receipt.read_text()) if receipt.is_file() else {}
    builds = []
    for build in previous.get('builds', []):
        if current['stage'] == 'all' or build['stage'] == current['stage']:
            continue
        retained = {name: value for name, value in build['artifacts'].items()
                    if name not in current['artifacts']}
        if retained:
            builds.append(dict(build, artifacts=retained))
    artifacts = {name: value for build in builds for name, value in build['artifacts'].items()}
    output = output.resolve()
    def target(name):
        path = (output/name).resolve()
        if output not in path.parents:
            raise ValueError('artifact escapes output directory')
        return path
    for name, expected in artifacts.items():
        data = target(name).read_bytes()
        if len(data) != expected['bytes'] or hashlib.sha256(data).hexdigest() != expected['sha256']:
            raise ValueError('retained artifact identity mismatch: '+name)
    # Check all destinations before replacing any delivered file.
    destinations = {name: target(name) for name in current['artifacts']}
    old_artifacts = previous.get('artifacts', {})
    obsolete = [target(name) for name in old_artifacts
                if name not in artifacts and name not in current['artifacts']]
    output.mkdir(parents=True, exist_ok=True)
    for name, path in destinations.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(work/name, path)
    for path in obsolete:
        path.unlink(missing_ok=True)
    builds.append(current)
    artifacts.update(current['artifacts'])
    record = {'schema': 1, 'board': current['board'], 'builds': builds, 'artifacts': artifacts}
    receipt.write_text(json.dumps(record, indent=2)+'\n')
    result = verify(output, receipt.name)
    (output/'verification.json').write_text(json.dumps(result, indent=2)+'\n')


def build_board(board, directory, config, stage, output, source_cache=None, jobs=4, inputs=None):
    required = {'uefi', 'efi'} if stage == 'all' else {stage}
    supported = config.get('supported_targets')
    if supported is not None and not required.issubset(supported):
        raise ValueError(config.get('unavailable_reason', 'selected board boot targets are not implemented'))
    builder = (directory/config['boot_builder']).resolve()
    boot = (directory/'boot').resolve()
    if boot not in builder.parents or not builder.is_file():
        raise ValueError('board boot builder must exist inside the linked boot project')
    work = REPO/'build/boot'/board
    output = output.resolve()
    if output == work.resolve() or work.resolve() in output.parents or output in work.resolve().parents:
        raise ValueError('artifact directory must be separate from the boot work directory')
    work.parent.mkdir(parents=True, exist_ok=True)
    with (work.parent/(board+'.lock')).open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if work.is_symlink():
            raise ValueError('boot work directory must not be a symlink')
        if work.exists():
            shutil.rmtree(work)
        argv = [sys.executable, str(builder), '--output', str(work.resolve()),
                '--stage', stage, '--jobs', str(jobs), '--kernel-source', str((directory/'kernel').resolve())]
        if source_cache:
            argv += ['--source-cache', str(source_cache.resolve())]
        default_inputs = directory/'boot-inputs.local.json'
        if stage != 'efi' and (inputs or default_inputs.is_file()):
            argv += ['--inputs', str((inputs or default_inputs).resolve())]
        subprocess.run(argv, check=True)
        publish(work, output)
        shutil.rmtree(work)
    print('Boot artifacts: '+str(output))


def main():
    registry = boards()
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['list', 'build'])
    p.add_argument('--board', choices=sorted(registry))
    p.add_argument('--stage', choices=['all', 'uefi', 'efi'], default='all')
    p.add_argument('--output', type=Path, help='artifact directory; default: build/artifacts/<board>/boot')
    p.add_argument('--source-cache', type=Path)
    p.add_argument('--jobs', type=int, default=4)
    p.add_argument('--inputs', type=Path, help='board-local boot packaging input JSON')
    a = p.parse_args()
    if a.action == 'list':
        for name, (_, config) in registry.items():
            print(f'{name}: {config["architecture"]}; profiles: {", ".join(config["profiles"])}')
        return
    if not a.board or a.jobs < 1:
        p.error('build requires --board and positive --jobs')
    directory, config = registry[a.board]
    output = a.output or REPO/'build/artifacts'/a.board/'boot'
    try:
        build_board(a.board, directory, config, a.stage, output, a.source_cache, a.jobs, a.inputs)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        p.exit(1, str(error)+'\n')


if __name__ == '__main__':
    main()
