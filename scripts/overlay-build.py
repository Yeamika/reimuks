#!/usr/bin/env python3
"""Build the configured board overlay set for one profile."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from overlay_registry import REPO, profile_name, selected_layers


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--board', default=os.environ.get('REIMUKS_BOARD', 'w202ds'))
    parser.add_argument('--profile', required=True)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    try:
        name = profile_name(args.profile)
        config, selected = selected_layers(args.board, name)
        builder = config.get('builder')
        match = [(root, descriptor) for reference, root, descriptor in selected
                 if reference == builder]
        if len(match) != 1:
            raise ValueError('Configured builder must be one selected overlay')
        root, descriptor = match[0]
        script_name = descriptor.get('build')
        if not script_name:
            raise ValueError('Selected builder overlay has no build entrypoint')
        script = (root/script_name).resolve()
        if not script.is_relative_to(root.resolve()) or not script.is_file():
            raise ValueError('Overlay build entrypoint is missing or escapes its layer')
        command = [sys.executable, str(script), '--profile', name]
        if args.config:
            command += ['--config', str(args.config.resolve())]
        if args.check:
            command.append('--check')
        subprocess.run(command, cwd=REPO, check=True)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
