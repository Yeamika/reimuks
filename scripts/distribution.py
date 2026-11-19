#!/usr/bin/env python3
"""Build a reusable distribution base without loading any board project."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
import build
import pack
from output_paths import temporary_environment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--distribution', default=build.DEFAULT)
    parser.add_argument('--offline', action='store_true', help='use authenticated cached packages only')
    parser.add_argument('--plan', action='store_true')
    args = parser.parse_args()
    build.select_distribution(args.distribution)
    root = build.shared_distribution()
    if args.plan:
        print(json.dumps({'distribution': build.DISTRIBUTION['id'],
                          'architecture': build.DISTRIBUTION['architecture'],
                          'rootfs': str(build.profile_directory('server')/'rootfs'),
                          'output': str(root/'artifacts/desktop-base-arm64-rootfs.tar.gz'),
                          'board_required': False}, indent=2))
        return
    os.environ.update(temporary_environment(root))
    with build.profile_lock('server'):
        work = build.profile_directory('server')/'work'
        if (work/'configured').exists():
            build.check_rootfs('server')
        else:
            if args.offline:
                if not (build.SHARED_BUILD/'tools/proot').is_file() or not (build.TOOLS/'usr/bin/qemu-aarch64').is_file():
                    parser.error('Prepare the shared build tools before an offline distribution build')
            else:
                build.prepare_tools()
            state = build.fetch('server', offline=args.offline)
            if not (build.profile_directory('server')/'rootfs').exists():
                build.assemble('server', state)
            build.configure('server', apply_account_config=False)
    pack.rootfs('server', base_only=True)
    from verify import verify_rootfs
    result = verify_rootfs(root/'artifacts/desktop-base-arm64-rootfs.tar.gz', 'server', True)
    build.write(root/'artifacts/base-verification.json', json.dumps(result, indent=2)+'\n')


if __name__ == '__main__':
    main()
