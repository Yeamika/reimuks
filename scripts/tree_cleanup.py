"""Remove owned staging directories, including mode-000 PRoot placeholders."""
import shutil
import os
import stat
from pathlib import Path


def remove_proot_placeholders(root):
    """Drop only owned, empty mode-000 mount placeholders after PRoot exits."""
    root = Path(root)
    for name in ('host-rootfs', 'packages', 'etc/ld.so.preload'):
        path = root/name
        if not path.exists() or path.is_symlink():
            continue
        info = path.lstat()
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0:
            continue
        if stat.S_ISREG(info.st_mode) and info.st_size == 0:
            path.unlink()
        elif stat.S_ISDIR(info.st_mode):
            path.chmod(0o700)
            try:
                path.rmdir()
            except OSError:
                path.chmod(0)
                raise ValueError('Nonempty PRoot placeholder: '+str(path))


def remove_tree(root):
    root = Path(root)
    if root.is_symlink() or root.resolve() == Path('/'):
        raise ValueError('Refusing unsafe staging directory removal')
    if not root.exists():
        return
    pending = [root]
    while pending:
        directory = pending.pop()
        mode = directory.lstat().st_mode
        if not stat.S_ISDIR(mode):
            continue
        directory.chmod(stat.S_IMODE(mode) | stat.S_IRWXU)
        for entry in directory.iterdir():
            if stat.S_ISDIR(entry.lstat().st_mode):
                pending.append(entry)
    shutil.rmtree(root)
