#!/usr/bin/env python3
"""Package a wallpaper and move the existing Plasma task panel to the left."""
import argparse
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import tarfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _package import archive_or_source

WALLPAPER = 'Pictures/Wallpapers/reimuks-wallpaper.png'
AUTOSTART = '.config/autostart/reimuks-kde-theme.desktop'
APPLY = '.local/bin/reimuks-kde-theme'

SCRIPT = '''#!/bin/sh
set -eu
image="$HOME/'''+WALLPAPER+'''"
test -r "$image"
layout='
var ps = panels();
var chosen;
for (var i = 0; i < ps.length; ++i) {
    var ws = ps[i].widgets();
    if (ws.some(function(w) {
        return w.type == "org.kde.plasma.icontasks" || w.type == "org.kde.plasma.taskmanager";
    })) {
        chosen = ps[i];
        if (chosen.screen == 0) break;
    }
}
if (!chosen) throw new Error("No Plasma task panel yet");
chosen.location = "left";
'
attempt=0
while [ "$attempt" -lt 30 ]; do
    if /usr/bin/plasma-apply-wallpaperimage "$image" &&
       /usr/bin/busctl --user call org.kde.plasmashell /PlasmaShell org.kde.PlasmaShell evaluateScript s "$layout"; then
        rm -f -- "$HOME/'''+AUTOSTART+'''"
        exit 0
    fi
    attempt=$((attempt+1))
    sleep 2
done
exit 1
'''


def home_for(account):
    if not re.fullmatch(r'[a-z_][a-z0-9_-]*', account):
        raise ValueError('Invalid KDE theme account')
    return PurePosixPath('home', account)


def settings(account):
    entry = ('[Desktop Entry]\nType=Application\nName=Apply personal Plasma layout\n'
             f'Exec=/home/{account}/{APPLY}\nOnlyShowIn=KDE;\n'
             'X-KDE-autostart-phase=2\nTerminal=false\n')
    return {WALLPAPER: (0o644, None), AUTOSTART: (0o644, entry.encode()), APPLY: (0o755, SCRIPT.encode())}


def check_theme(entries, open_member):
    users = {PurePosixPath(name).parts[1] for name in entries if name.startswith('home/')}
    if len(users) != 1:
        raise ValueError('KDE theme must target one home directory')
    account, = users
    expected = {str(home_for(account)/name): spec for name, spec in settings(account).items()}
    parents = {str(p) for name in expected for p in PurePosixPath(name).parents}
    if (entries.keys() - expected.keys() - parents) or not expected.keys() <= entries.keys():
        raise ValueError('KDE theme may contain only its wallpaper and layout launcher')
    for name, member in entries.items():
        if name in parents:
            if not member.isdir() or member.mode & 0o7022:
                raise ValueError('Invalid KDE theme directory')
            continue
        mode, content = expected[name]
        if not member.isfile() or member.mode & 0o7777 != mode:
            raise ValueError('Invalid KDE theme file')
        with open_member(member) as stream:
            if content is None:
                matches = 8 < member.size <= 32*1024*1024 and stream.read(8) == b'\x89PNG\r\n\x1a\n'
            else:
                matches = member.size == len(content) and stream.read(len(content)) == content
            if not matches:
                raise ValueError('Unexpected KDE theme content')


def create_source(work, wallpaper, account):
    wallpaper = wallpaper.expanduser()
    if wallpaper.is_dir():
        wallpaper = wallpaper/'wallpaper.png'
    source = work/'wallpaper-source'
    for name, (mode, content) in settings(account).items():
        path = source/home_for(account)/name
        path.parent.mkdir(parents=True, exist_ok=True)
        if content is None:
            shutil.copyfile(wallpaper, path)
        else:
            path.write_bytes(content)
        path.chmod(mode)
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--wallpaper', '--input', type=Path,
                        help='Private PNG or directory containing wallpaper.png')
    source.add_argument('--archive', type=Path, help='Reuse an existing KDE theme archive')
    parser.add_argument('--account', default='reimuks')
    parser.add_argument('--output', type=Path, required=True, help='New private package directory')
    args = parser.parse_args()
    try:
        archive_or_source(lambda work: create_source(work, args.wallpaper, args.account),
                          args.archive, args.output, 'kde-theme', ['desktop-kde'], check_theme)
    except (OSError, ValueError, tarfile.TarError) as error:
        parser.exit(1, f'{parser.prog}: {error}\n')
    print(args.output)


if __name__ == '__main__':
    main()
