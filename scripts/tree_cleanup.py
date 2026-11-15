"""Remove owned staging directories, including mode-000 PRoot placeholders."""
import shutil
import stat
from pathlib import Path


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
