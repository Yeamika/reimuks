#!/usr/bin/env python3
"""Package MIX 2S board services and hardware interfaces."""
import argparse
import os
from pathlib import Path
import sys

LAYER = Path(__file__).resolve().parent
sys.path.insert(0, str(LAYER.parents[3]/'scripts'))
from overlay_package import portable, stage_policy, staging


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--architecture', required=True, choices=['arm64'])
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    os.umask(0o022)
    try:
        with staging(args.output) as (root, export):
            stage_policy(root, LAYER, 'board')
            portable(root, export, 'polaris-hardware', 'polaris-hardware.tar.gz',
                     'all', ['kernel', 'distribution'], board='polaris')
    except (OSError, ValueError) as error:
        parser.exit(1, f'{parser.prog}: {error}\n')


if __name__ == '__main__':
    main()
