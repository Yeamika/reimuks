#!/usr/bin/env python3
"""Package private user files separately and merge them into a deployment archive."""
import argparse
import gzip
import io
import os
from pathlib import Path, PurePosixPath
import tarfile


def validate(members):
    entries = {}
    for member in members:
        name = member.name.removeprefix('./').rstrip('/')
        path = PurePosixPath(name)
        if name in ('', '.'):
            continue
        if path.is_absolute() or '..' in path.parts or str(path) != name:
            raise ValueError('Unsafe archive path: '+name)
        if name in entries:
            raise ValueError('Duplicate archive path: '+name)
        if not (member.isfile() or member.isdir() or member.issym()):
            raise ValueError('Overlay supports only files, directories and symbolic links: '+name)
        entries[name] = member
    for name in entries:
        for parent in PurePosixPath(name).parents:
            if str(parent) in entries and not entries[str(parent)].isdir():
                raise ValueError('Archive traverses a non-directory: '+name)
    return entries


def archive(output, emit):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(output.name+'.part')
    try:
        with partial.open('wb') as raw, gzip.GzipFile(filename='', fileobj=raw, mode='wb', mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode='w|', format=tarfile.PAX_FORMAT) as result:
                emit(result)
        partial.replace(output)
        output.chmod(0o600)
    finally:
        partial.unlink(missing_ok=True)


def pack(source, output):
    source = Path(source).resolve()
    output = Path(output).resolve()
    if not source.is_dir() or output.is_relative_to(source):
        raise ValueError('Use a source directory and an output outside it')
    def emit(result):
        paths = sorted(source.rglob('*'))
        entries = [result.gettarinfo(str(p), str(p.relative_to(source))) for p in paths]
        validate(entries)
        for path, info in zip(paths, entries):
            info.uid = info.gid = 0
            info.uname = info.gname = ''
            info.mtime = 0
            if info.isfile():
                with path.open('rb') as stream:
                    result.addfile(info, stream)
            else:
                result.addfile(info)
    archive(output, emit)


def merge_passwords(base, private):
    """Patch login accounts without replacing newly added system accounts."""
    updates = {}
    for line in private.decode().splitlines():
        fields = line.split(':')
        if not line:
            continue
        if len(fields) != 9:
            raise ValueError('Invalid private shadow record')
        if fields[0] in ('root', 'reimuks'):
            if fields[0] in updates:
                raise ValueError('Duplicate private login account')
            updates[fields[0]] = line
    lines = base.decode().splitlines()
    names = {line.split(':', 1)[0] for line in lines}
    if updates.keys()-names:
        raise ValueError('Private login account is absent from the base')
    return ('\n'.join(updates.get(line.split(':',1)[0],line) for line in lines)+'\n').encode()


def merge(base, overlay, output):
    if Path(output).resolve() in (Path(base).resolve(), Path(overlay).resolve()):
        raise ValueError('Deployment output must differ from input archives')
    with tarfile.open(overlay, 'r:gz') as private, tarfile.open(base, 'r:gz') as original:
        additions = validate(private.getmembers())
        # Inspect the combined tree before emitting anything. Never allow a
        # private child to land beneath a base symlink or replace a directory.
        base_entries = {m.name.removeprefix('./').rstrip('/'): m for m in original}
        for name, info in additions.items():
            existing = base_entries.get(name)
            if existing is not None and existing.isdir() != info.isdir():
                raise ValueError('Overlay changes directory type: '+name)
            for parent in PurePosixPath(name).parents:
                ancestor = additions.get(str(parent), base_entries.get(str(parent)))
                if ancestor is not None and not ancestor.isdir():
                    raise ValueError('Overlay traverses a non-directory: '+name)
        users = {}
        passwd = base_entries.get('etc/passwd')
        if passwd is not None:
            for line in original.extractfile(passwd).read().decode().splitlines():
                fields = line.split(':')
                if len(fields) >= 4:
                    users[fields[0]] = (int(fields[2]), int(fields[3]))
        shadow = None
        if 'etc/shadow' in additions:
            if 'etc/shadow' not in base_entries or not additions['etc/shadow'].isfile():
                raise ValueError('Password overlay requires regular shadow files')
            shadow = merge_passwords(original.extractfile(base_entries['etc/shadow']).read(),
                                     private.extractfile(additions['etc/shadow']).read())
        def emit(result):
            # Reopen for sequential extraction rather than seeking repeatedly
            # through a compressed base image.
            with tarfile.open(base, 'r|gz') as stream:
                for info in stream:
                    name = info.name.removeprefix('./').rstrip('/')
                    if name in additions and not info.isdir():
                        continue
                    result.addfile(info, stream.extractfile(info) if info.isfile() else None)
            for name, info in additions.items():
                if info.isdir() and name in base_entries:
                    continue  # Preserve package directory permissions/ownership.
                if name.startswith('home/'):
                    account = PurePosixPath(name).parts[1]
                    if account not in users:
                        raise ValueError('Overlay references an unknown account: '+account)
                    info.uid, info.gid = users[account]
                elif name in base_entries:
                    info.uid, info.gid = base_entries[name].uid, base_entries[name].gid
                else:
                    info.uid = info.gid = 0
                info.uname = info.gname = ''
                if name == 'etc/shadow':
                    info.size = len(shadow)
                    result.addfile(info, io.BytesIO(shadow))
                else:
                    result.addfile(info, private.extractfile(info) if info.isfile() else None)
        archive(output, emit)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest='action', required=True)
    create = actions.add_parser('pack')
    create.add_argument('--source', type=Path, required=True)
    create.add_argument('--output', type=Path, required=True)
    combine = actions.add_parser('merge')
    combine.add_argument('--base', type=Path, required=True)
    combine.add_argument('--overlay', type=Path, required=True)
    combine.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.action == 'pack':
        pack(args.source, args.output)
    else:
        merge(args.base, args.overlay, args.output)


if __name__ == '__main__':
    os.umask(0o077)
    main()
