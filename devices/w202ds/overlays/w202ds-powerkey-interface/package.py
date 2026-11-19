#!/usr/bin/env python3
"""Package the W202DS hardware interface used by the power-key overlay."""
import argparse
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
LAYER = Path(__file__).resolve().parent
sys.path.insert(0, str(LAYER.parents[3]/'scripts'))
from board_userspace import install_template
from overlay_package import portable, staging


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--architecture', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    os.umask(0o022)
    try:
        with staging(args.output) as (root, export):
            install_template(root, LAYER/'files')
            portable(root, export, 'powerkey-interface', 'powerkey-interface-w202ds.tar.gz',
                     'all', ['kernel'], board='w202ds')
    except (OSError, ValueError) as error:
        parser.exit(1, f'{parser.prog}: {error}\n')


if __name__ == '__main__':
    main()
