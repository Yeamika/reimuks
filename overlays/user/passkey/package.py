#!/usr/bin/env python3
"""Package explicitly provided login, SSH and network settings."""
import argparse
import os
from pathlib import Path, PurePosixPath
import re
import sys
import tarfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _package import archive_or_source


REGION = 'etc/modprobe.d/w202-regdom.conf'
FILES = ('etc/shadow', 'etc/hostname', 'etc/hosts', REGION)
DIRECTORIES = ('etc/ssh', 'etc/NetworkManager/system-connections',
               'var/lib/NetworkManager', 'root/.ssh')


def validate_scope(entries, open_member):
    scopes = set(DIRECTORIES)
    for name in entries:
        parts = PurePosixPath(name).parts
        if len(parts) >= 3 and parts[0] == 'home' and parts[2] == '.ssh':
            scopes.add('/'.join(parts[:3]))
    parents = {str(p) for name in (*FILES, *scopes) for p in PurePosixPath(name).parents}
    files = 0
    for name, member in entries.items():
        child = any(name.startswith(scope+'/') for scope in scopes)
        if member.isdir() and (child or name in scopes or name in parents):
            continue
        if not member.isfile() or not (child or name in FILES):
            raise ValueError('Passkey accepts only regular login and network files; split device data and desktop settings first')
        files += 1
        if name == REGION:
            with open_member(member) as stream:
                if not re.fullmatch(rb'options cfg80211 ieee80211_regdom=[A-Z]{2}\n?', stream.read(65)):
                    raise ValueError('Invalid passkey Wi-Fi regulatory setting')
    if not files:
        raise ValueError('Passkey archive contains no login or network files')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--source', '--input', type=Path,
                        help='Private directory of login and network files')
    source.add_argument('--archive', type=Path, help='Reuse an existing passkey archive')
    parser.add_argument('--board', help='Optional board constraint for board-specific credentials/settings')
    parser.add_argument('--output', type=Path, required=True, help='New private package directory')
    args = parser.parse_args()
    board = args.board or os.environ.get('REIMUKS_BOARD') or None
    if board and not re.fullmatch(r'[a-z0-9][a-z0-9._-]*', board):
        parser.error('Invalid board identifier')
    try:
        archive_or_source(lambda _: args.source.expanduser(), args.archive, args.output,
                          'passkey', ['distribution'], validate_scope, board)
    except (OSError, ValueError, tarfile.TarError) as error:
        parser.exit(1, f'{parser.prog}: {error}\n')
    print(args.output)


if __name__ == '__main__':
    main()
