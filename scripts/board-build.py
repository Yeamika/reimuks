#!/usr/bin/env python3
"""Build and stage the hardware userspace API exported by a board provider."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from kernel import tool_environment
from board_exports import manifest, relative_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--board', type=Path, required=True)
    parser.add_argument('--cc', default=os.environ.get('CC', 'aarch64-linux-gnu-gcc'))
    parser.add_argument('--config', type=Path)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    root, description = manifest(args.board.resolve())
    build = description['build']
    settings = json.loads(args.config.read_text()) if args.config and args.config.exists() else {}
    producers = []
    for producer in build.get('producers', []):
        name = producer['name']
        inputs = settings.get('hardware_producers', {}).get(name)
        if not isinstance(inputs, dict):
            parser.error('Missing hardware_producers.'+name+' in local build config')
        script = relative_path(root, producer['script'])
        if not script.is_file():
            parser.error('Missing hardware producer: '+name)
        prefix = inputs.get('command_prefix', [sys.executable])
        arguments = inputs.get('arguments', [])
        if (not isinstance(prefix, list) or not prefix or not isinstance(arguments, list) or
                not all(isinstance(v, str) for v in [*prefix, *arguments])):
            parser.error('Invalid producer command inputs: '+name)
        producers.append((name, [*prefix, str(script), *arguments]))
    if args.check:
        print('Hardware producer inputs checked.')
        return
    command = list(build['command'])
    output = relative_path(root, build['output'])
    # Sources, compiler and output are explicit inputs; never invoke services.
    subprocess.run([*command, 'all', 'install', 'CC='+args.cc,
                    'OUT='+str(output), 'PYTHON='+sys.executable], cwd=root, env=tool_environment(), check=True)
    for name, producer_command in producers:
        print('Building hardware producer: '+name, flush=True)
        subprocess.run(producer_command, cwd=root, env=tool_environment(), check=True)


if __name__ == '__main__':
    main()
