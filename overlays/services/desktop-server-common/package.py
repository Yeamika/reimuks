#!/usr/bin/env python3
"""Package the shared console and power-key policy for the server presets."""
import argparse
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
LAYER = Path(__file__).resolve().parent
sys.path.insert(0, str(LAYER.parents[2]/'scripts'))
from overlay_package import portable, stage_policy, staging


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--architecture', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    os.umask(0o022)
    try:
        with staging(args.output) as (root, export):
            stage_policy(root, LAYER, 'server-common')
            portable(root, export, 'server-common', 'desktop-server-common.tar.gz',
                     'all', ['distribution', 'powerkey', 'powerkey-interface'])
    except (OSError, ValueError) as error:
        parser.exit(1, f'{parser.prog}: {error}\n')


if __name__ == '__main__':
    main()
