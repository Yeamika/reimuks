"""Install desktop API policy; hardware drivers belong to board providers."""
from pathlib import Path


def install(root, profile, distribution):
    from distributions import profile_name
    extra = distribution.get('additional_packages', {})
    if profile_name(profile) not in extra.get('profiles', []):
        return
    desktop = root/'usr/share/applications/google-chrome.desktop'
    if not desktop.is_file():
        for relative in ('usr/bin/reimuks-chrome', 'etc/skel/.local/share/applications/google-chrome.desktop'):
            (root/relative).unlink(missing_ok=True)
        return
    source = Path(__file__).resolve().parents[1]/'overlays/apps/remote/files'
    from board_userspace import install_template
    install_template(root, source)
    desktop = root/'usr/share/applications/google-chrome.desktop'
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
