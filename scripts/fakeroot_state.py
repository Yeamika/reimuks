"""Retain package ownership while dropping stale inode metadata after host staging."""
from pathlib import Path
import stat


def snapshot(root):
    result = {}
    for path in [root, *root.rglob('*')]:
        info = path.lstat()
        result[str(path.relative_to(root))] = (info.st_dev, info.st_ino,
            info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    return result


def reconcile(source, destination, root, previous):
    current = snapshot(root)
    changed = set()
    types = {}
    for name, info in current.items():
        key = info[:2]
        types[key] = stat.S_IFMT(info[2])
        old = previous.get(name)
        # Adding children changes directory timestamps but not its ownership.
        unchanged = old is not None and (old[:3] == info[:3] if stat.S_ISDIR(info[2]) else old == info)
        if not unchanged:
            changed.add(key)
    retained = []
    for line in source.read_text().splitlines():
        fields = dict(field.split('=', 1) for field in line.split(','))
        key = (int(fields['dev'], 16), int(fields['ino']))
        fake_type = stat.S_IFMT(int(fields['mode'], 8))
        actual = types.get(key)
        # fakeroot legitimately represents mknod objects as ordinary host files.
        compatible = actual == fake_type or (actual == stat.S_IFREG and fake_type in (stat.S_IFCHR, stat.S_IFBLK, stat.S_IFIFO))
        if key not in changed and compatible:
            retained.append(line)
    destination.write_text(''.join(line+'\n' for line in retained))
    return len(retained)
