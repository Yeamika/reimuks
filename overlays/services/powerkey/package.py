#!/usr/bin/env python3
"""Package the shared power-key service without a board or a distro rootfs."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
LAYER = Path(__file__).resolve().parent
sys.path.append(str(LAYER.parents[2]/'scripts'))
# The legacy board build and the standalone package use the same compiler entry.
from build import TARGETS, compile_helper, compiler
from board_userspace import controls_binary
from output_paths import shared_root
from overlay_package import portable, staging


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--architecture', required=True, choices=sorted(TARGETS))
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--cc')
    args = parser.parse_args()
    os.umask(0o022)
    try:
        with staging(args.output) as (root, export):
            shutil.copytree(LAYER/'files/usr', root/'usr', symlinks=True)
            binary = root/'usr/libexec/reimuks-powerkey'
            compile_helper(binary, compiler(args.cc, args.architecture),
                           shared_root()/'cache/powerkey'/args.architecture)
            controls_binary(root, binary.name, args.architecture)
            portable(root, export, 'powerkey', f'powerkey-{args.architecture}.tar.gz',
                     args.architecture, ['distribution'])
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'{parser.prog}: {error}\n')


if __name__ == '__main__':
    main()
