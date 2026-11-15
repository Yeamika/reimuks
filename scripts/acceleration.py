"""Install desktop API policy; hardware drivers belong to board providers."""
from pathlib import Path
import shutil


def install(root, profile, distribution):
    from distributions import profile_name
    extra = distribution.get('additional_packages', {})
    if profile_name(profile) not in extra.get('profiles', []):
        return
    source = Path(__file__).resolve().parents[1]/'distributions'/distribution['id']/'rootfs'
    shutil.copytree(source, root, dirs_exist_ok=True, symlinks=True)
    desktop = root/'usr/share/applications/google-chrome.desktop'
    if not desktop.is_file():
        raise ValueError('Missing installed Google Chrome desktop entry')
    text = desktop.read_text()
    lines = []
    for line in text.splitlines():
        if line.startswith('Exec='):
            for binary in ('/usr/bin/google-chrome-stable', '/usr/bin/google-chrome'):
                line = line.replace(binary, '/usr/bin/reimuks-chrome')
        lines.append(line)
    target = root/'etc/skel/.local/share/applications/google-chrome.desktop'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('\n'.join(lines)+'\n')
