#!/usr/bin/env python3
"""Package the ARM64 rexed service and a private TLS identity."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import ssl
import sys
import tarfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _package import archive_or_source


BINARY = 'usr/bin/rexed'
CONFIG = 'home/reimuks/.config/rexed'
UNIT = 'usr/lib/systemd/system/rexed.service'
LOGS = '/var/log/rexed'


def copy_input(source, dest, mode):
    if source.is_symlink() or not source.is_file() or not source.stat().st_size:
        raise ValueError(f'Expected a nonempty regular file: {source}')
    shutil.copyfile(source, dest)
    dest.chmod(mode)


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2)+'\n')
    path.chmod(0o600)


def stage(work, inputs):
    root = work/'rootfs'
    binary, config, unit = root/BINARY, root/CONFIG, root/UNIT
    client = config/'users'/'reimuks'
    link = root/'etc/systemd/system/multi-user.target.wants/rexed.service'
    for directory in (binary.parent, client, unit.parent, link.parent):
        directory.mkdir(parents=True)
    # Only the explicit server material and public client certificate enter the layer.
    for directory in root.rglob('*'):
        if directory.is_dir():
            directory.chmod(0o700 if directory.is_relative_to(config) else 0o755)
    copy_input(inputs/'rexed', binary, 0o755)
    cert, key = config/'server-cert.pem', config/'server-key.pem'
    copy_input(inputs/cert.name, cert, 0o600)
    copy_input(inputs/key.name, key, 0o600)
    ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(cert, key, password='')

    public = client/'client-cert.pem'
    copy_input(inputs/public.name, public, 0o600)
    leaf = public.read_bytes().strip()
    if not re.fullmatch(rb'-----BEGIN CERTIFICATE-----\s+[A-Za-z0-9+/=\r\n]+'
                        rb'-----END CERTIFICATE-----', leaf):
        raise ValueError('client-cert.pem must contain only one public PEM certificate')
    ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT).load_verify_locations(cadata=leaf.decode('ascii'))
    write_json(config/'server.json', {'certificate': cert.name, 'privateKey': key.name,
                                     'logging': {'directory': LOGS}})
    write_json(client/'config.json', {'certificates': [public.name], 'permissions': {
        'execute': True, 'filesRead': True, 'filesWrite': True,
        'ptyView': True, 'ptyControl': True, 'forward': True,
    }})
    copy_input(Path(__file__).with_name('rexed.service'), unit, 0o644)
    link.symlink_to('/'+UNIT)
    return root


def check_binary(entries, open_member):
    with open_member(entries[BINARY]) as binary:
        header = binary.read(20)
    if (not header.startswith(b'\x7fELF\x02\x01\x01') or
            header[16:18] not in (b'\x02\x00', b'\x03\x00') or header[18:20] != b'\xb7\x00'):
        raise ValueError('rexed must be an ARM64 Linux ELF executable')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True,
                        help='Directory with rexed, server-cert.pem, server-key.pem and client-cert.pem')
    parser.add_argument('--output', type=Path, required=True, help='New private package directory')
    args = parser.parse_args()
    try:
        archive_or_source(lambda work: stage(work, args.input.expanduser()), None, args.output,
                          'rexeterm', ['distribution'], check_binary,
                          os.environ.get('REIMUKS_BOARD') or None, architecture='arm64')
    except (OSError, ValueError, tarfile.TarError) as error:
        parser.exit(1, f'{parser.prog}: {error}\n')
    print(args.output)


if __name__ == '__main__':
    main()
