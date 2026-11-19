#!/usr/bin/env python3
"""Build the shared power-key service with Polaris' board adapter."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

LAYER = Path(__file__).resolve().parent
REPO = LAYER.parents[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=['server'], required=True)
    parser.add_argument('--config', type=Path, default=LAYER / 'build.local.json')
    parser.add_argument('--cc')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()

    settings = json.loads(args.config.read_text()) if args.config.is_file() else {}
    cc = args.cc or settings.get('cc', 'zig cc -target aarch64-linux-musl -static')
    builder = REPO / 'overlays/services/powerkey/build.py'
    command = [sys.executable, str(builder), '--board', 'polaris', '--cc', cc]
    if args.config:
        command += ['--config', str(args.config.resolve())]
    if args.check:
        command.append('--check')
    subprocess.run(command, cwd=REPO, check=True)


if __name__ == '__main__':
    main()
