#!/usr/bin/env python3
"""Build the shared power-key service into the selected board build root."""
import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

LAYER = Path(__file__).resolve().parent
REPO = LAYER.parents[2]
sys.path.insert(0, str(REPO / 'scripts'))
from output_paths import board_root


TARGETS = {'arm64': 'aarch64-linux-musl', 'x86_64': 'x86_64-linux-musl'}
SOURCE = LAYER/'src/reimuks-powerkey.c'


def compiler(cc, architecture='arm64'):
    command = shlex.split(cc or f'zig cc -target {TARGETS[architecture]} -static')
    if not SOURCE.is_file() or not SOURCE.with_name('powerkey-state.h').is_file():
        raise ValueError('shared power-key source files are incomplete')
    if not command or not shutil.which(command[0]):
        raise ValueError('target C compiler not found: ' + (command[0] if command else str(cc)))
    return command


def compile_helper(binary, command, cache):
    binary.parent.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(cache/'global'),
               ZIG_LOCAL_CACHE_DIR=str(cache/'local'))
    temporary = binary.with_suffix('.new')
    subprocess.run([
        *command, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
        str(SOURCE), '-o', str(temporary)
    ], check=True, env=env)
    temporary.replace(binary)
    binary.chmod(0o755)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--board', required=True)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--cc')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()

    settings = json.loads(args.config.read_text()) if args.config and args.config.is_file() else {}
    try:
        command = compiler(args.cc or settings.get('cc'))
    except ValueError as error:
        parser.error(str(error))
    if args.check:
        print('Shared power-key build inputs checked; no compilation performed.')
        return

    work = board_root(args.board)
    binary = work/'powerkey/rootfs/usr/libexec/reimuks-powerkey'
    compile_helper(binary, command, work/'cache/powerkey')
    print(binary)


if __name__ == '__main__':
    main()
