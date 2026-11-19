#!/usr/bin/env python3
"""Build W202DS system integration; SDK paths are local build inputs."""
import argparse
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys

LAYER = Path(__file__).resolve().parent
BOARD = LAYER.parents[1]
REPO = BOARD.parents[1]
sys.path.insert(0, str(REPO/'scripts'))
from kernel import tool_environment
from output_paths import board_root, shared_root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', required=True)
    parser.add_argument('--config', type=Path, default=LAYER/'build.local.json')
    parser.add_argument('--check', action='store_true', help='Check build inputs without compiling')
    args = parser.parse_args()
    settings = json.loads(args.config.read_text()) if args.config.exists() else {}
    output = board_root('w202ds')
    default_proot = str(shared_root()/'tools/proot')
    def path(value):
        return str((REPO/value).resolve())
    cc = path(settings['cc']) if settings.get('cc') else os.environ.get('CC', 'aarch64-linux-gnu-gcc')
    errors = []
    if not shutil.which(cc, path=tool_environment().get('PATH')):
        errors.append('target C compiler not found: '+cc)
    for directory in settings.get('library_dirs', []):
        if not Path(path(directory)).is_dir():
            errors.append('library directory not found: '+directory)
    if args.profile in ('kde', 'desktop/kde'):
        sdk = settings.get('desktop_sysroot')
        if not sdk:
            errors.append('KDE requires desktop_sysroot in the local build config')
        else:
            for include in ('aarch64-linux-gnu/qt6/QtCore/qobject.h',
                            'KF6/KScreen/kscreen/config.h', 'libudev.h'):
                if not (Path(path(sdk))/'usr/include'/include).is_file():
                    errors.append('target SDK header not found: '+include)
        if settings.get('desktop_host_root'):
            host = Path(path(settings['desktop_host_root']))
            if not (host/'usr/bin/python3').exists():
                errors.append('desktop_host_root has no Python interpreter')
            if not Path(path(settings.get('proot', default_proot))).is_file():
                errors.append('desktop host runner not found; prepare build tools first')
            if settings.get('moc') and not (host/settings['moc'].lstrip('/')).is_file():
                errors.append('moc not found in desktop_host_root')
    if errors:
        parser.exit(2, 'Build input check failed:\n  - '+'\n  - '.join(errors)+'\n')
    hardware_command = [sys.executable, str(REPO/'scripts/board-build.py'),
                        '--board', str(BOARD), '--cc', cc, '--config', str(args.config)]
    subprocess.run([*hardware_command, '--check'], check=True)
    powerkey_command = [sys.executable, str(REPO/'overlays/services/powerkey/build.py'),
                        '--board', 'w202ds', '--cc', cc]
    if args.config.exists():
        powerkey_command += ['--config', str(args.config)]
    powerkey_env = tool_environment('w202ds')
    subprocess.run([*powerkey_command, '--check'], env=powerkey_env, check=True)
    if args.check:
        print('Build inputs checked; no compilation performed.')
        return
    subprocess.run(hardware_command, check=True)
    subprocess.run(powerkey_command, env=powerkey_env, check=True)
    link = []
    for directory in settings.get('library_dirs', []):
        link += ['-L'+path(directory)]
    link += settings.get('ldflags', [])
    profile = args.profile.removeprefix('desktop/')
    if profile in ('server', 'kde', 'gnome'):
        controls = [('overlays/w202ds-hardwarepack2/src/device-controls', 'device-controls')]
        if profile == 'server':
            controls.append(('overlays/w202ds-hall-overlay/src/hall', 'server-hall'))
        if profile in ('kde', 'gnome'):
            controls.append(('overlays/w202ds-kde-hardwareuipack/src/kde/session' if profile == 'kde'
                             else 'overlays/w202ds-gnome-hardwareuipack/src/gnome',
                             'desktop-'+profile))
        for source, destination in controls:
            subprocess.run(['make', '-C', str(BOARD/source),
                            'stage', 'CC='+cc, 'PYTHON='+sys.executable,
                            'OUT='+str(output/destination),
                            'LDFLAGS='+' '.join(link)], env=tool_environment('w202ds'), check=True)
    if args.profile in ('kde', 'desktop/kde'):
        sdk = settings.get('desktop_sysroot')
        if not sdk:
            raise ValueError('KDE requires desktop_sysroot in the local build config')
        command = [sys.executable, str(BOARD/'overlays/w202ds-kde-hardwareuipack/src/kde/build.py'), '--sysroot', path(sdk),
                   '--output', str(output/'desktop-kde')]
        if settings.get('desktop_host_root'):
            proot = path(settings.get('proot', default_proot))
            output.mkdir(parents=True, exist_ok=True)
            command = [proot, '-r', path(settings['desktop_host_root']),
                       '-b', str(REPO), '-b', str(output), '-b', path(sdk),
                       '-b', '/dev', '-b', '/proc', '-w', str(REPO),
                       '/usr/bin/env', 'PATH=/usr/bin:/bin', '/usr/bin/python3',
                       *command[1:]]
        if settings.get('moc'):
            command += ['--moc', settings['moc']]
        if settings.get('cxx'):
            command += ['--cxx', settings['cxx']]
        subprocess.run(command, env=tool_environment('w202ds'), check=True)


if __name__ == '__main__':
    main()
