"""Translate a published portable overlay into a Debian package."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile

import build
from compose_target import existing_file
from layers import package_tree
from user_overlay import validate


def unpack(receipt, root):
    record = json.loads(receipt.read_text())
    archives = [name for name in record['files'] if name.endswith('.tar.gz')]
    if len(archives) != 1:
        raise ValueError(f'Expected one overlay archive in {receipt}')
    name, = archives
    payload = existing_file(receipt.parent.resolve(), name)
    if build.digest(payload) != record['files'][name]:
        raise ValueError(f'Overlay hash mismatch: {payload}')
    with tarfile.open(payload, 'r:gz') as archive:
        entries = validate(archive.getmembers())
        for name, member in sorted(entries.items()):
            path = root/name
            if member.isdir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                if member.issym():
                    path.symlink_to(member.linkname)
                else:
                    with archive.extractfile(member) as source, path.open('xb') as target:
                        shutil.copyfileobj(source, target)
            if not member.issym():
                path.chmod(member.mode & 0o755)


def adapt(receipt, output, *, name, depends, kind, postinst=None, **control):
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.deb-layer-', dir=output) as work:
        root = Path(work)/'root'
        root.mkdir(mode=0o755)
        unpack(receipt, root)
        if postinst:
            build.write(root/'DEBIAN/postinst', '#!/bin/sh\nset -eu\n'
                        'if [ "$1" = configure ]; then\n'+postinst+'\nfi\n', 0o755)
        return package_tree(root, output, name, depends, kind, **control)


def record_deb(directory, relative):
    path = existing_file(directory.resolve(), relative)
    fields = subprocess.check_output(['dpkg-deb', '-f', str(path), 'Package', 'Version',
                                      'Architecture'], text=True)
    fields = dict(line.split(': ', 1) for line in fields.splitlines())
    return dict(package=fields['Package'], version=fields['Version'],
                architecture=fields['Architecture'], sha256=build.digest(path), file=relative)


def reuse_package(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def shared_powerkey(receipt, output, architecture):
    # The previous offline package owned the unit and binaries.
    old_server = ['reimuks-desktop-server-common (<< 1.1)']
    return adapt(receipt, output, name='reimuks-powerkey', kind='powerkey',
                 architecture=architecture, depends=['systemd', 'udev', 'python3'],
                 breaks=old_server, replaces=old_server)
