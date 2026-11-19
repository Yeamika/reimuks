#!/usr/bin/env python3
"""Build KDE integration against an explicitly supplied target SDK."""
import argparse
import os
from pathlib import Path
import shlex
import subprocess
import sys

SOURCE = Path(__file__).resolve().parent
REPO = SOURCE.parents[5]
sys.path.insert(0, str(REPO/'scripts'))
from output_paths import board_root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sysroot', type=Path, required=True)
    parser.add_argument('--output', type=Path, help='default: <board-build>/desktop-kde')
    parser.add_argument('--cxx', default=os.environ.get('CXX', 'aarch64-linux-gnu-g++'))
    parser.add_argument('--moc', default='moc')
    parser.add_argument('--library-dir', type=Path, action='append', default=[])
    args = parser.parse_args()
    sdk = args.sysroot.resolve()
    out = (args.output or board_root('w202ds')/'desktop-kde').resolve()
    out.mkdir(parents=True, exist_ok=True)
    includes = [sdk/'usr/include'/name for name in (
        'aarch64-linux-gnu/qt6', 'aarch64-linux-gnu/qt6/QtCore',
        'aarch64-linux-gnu/qt6/QtDBus', 'aarch64-linux-gnu/qt6/QtGui',
        'aarch64-linux-gnu/qt6/QtWidgets', 'aarch64-linux-gnu/qt6/QtQml', 'aarch64-linux-gnu/qt6/QtQmlIntegration',
        'KF6/KCoreAddons', 'KF6/KScreen', 'KF6/KSvg',
        'KF6/KConfig', 'KF6/KConfigCore', 'ksysguard')]
    flags = ['-std=c++17', '-fPIC', '--sysroot='+str(sdk),
             '-I'+str(out), *['-I'+str(p) for p in includes]]
    libraries = [sdk/'usr/lib/aarch64-linux-gnu', *[p.resolve() for p in args.library_dir]]
    link = ['-L'+str(p) for p in libraries]
    link += ['-Wl,-rpath-link,'+str(p) for p in libraries]
    # Shared Qt dependencies are resolved by the target distro's runtime loader.
    link += ['-Wl,--allow-shlib-undefined']
    stats = SOURCE/'vpu-stats'
    subprocess.run([args.moc, *['-I'+str(p) for p in includes],
                    str(stats/'plugin.cpp'), '-o', str(out/'plugin.moc')], check=True)
    subprocess.run([args.moc, *['-I'+str(p) for p in includes],
                    str(SOURCE/'popup-cache/plugin.cpp'),
                    '-o', str(out/'popup-cache.moc')], check=True)
    targets = [
        (SOURCE/'popup-cache/plugin.cpp', 'libpopupcache.so',
         ['-shared', '-l:libQt6Core.so.6', '-l:libQt6Qml.so.6',
          '-l:libKF6Svg.so.6']),
        (stats/'plugin.cpp', 'ksystemstats_plugin_w202_vpu.so',
         ['-shared', '-l:libQt6Core.so.6', '-l:libQt6DBus.so.6',
          '-l:libKF6CoreAddons.so.6', '-l:libKSysGuardSystemStats.so.2']),
        (SOURCE/'rotation/main.cpp', 'w202-rotation',
         ['-l:libQt6Widgets.so.6', '-l:libQt6Gui.so.6', '-l:libQt6Core.so.6',
          '-l:libQt6DBus.so.6', '-l:libKF6Screen.so.8', '-l:libudev.so.1']),
    ]
    for source, name, options in targets:
        subprocess.run([*shlex.split(args.cxx), *flags, str(source), *link,
                        *options, '-o', str(out/name)], check=True)
    root = out/'rootfs'
    destinations = {
        'libpopupcache.so': 'usr/lib/aarch64-linux-gnu/qt6/qml/org/reimuks/popupcache',
        'ksystemstats_plugin_w202_vpu.so': 'usr/lib/aarch64-linux-gnu/qt6/plugins/ksystemstats',
        'w202-rotation': 'usr/bin',
    }
    import shutil
    for name, directory in destinations.items():
        target = root/directory/name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(out/name, target)
    shutil.copy2(SOURCE/'popup-cache/qmldir',
                 root/destinations['libpopupcache.so']/'qmldir')
    for name, directory in [('w202-rotation.desktop', 'applications'),
                            ('w202-rotation-watch.desktop', 'w202-rotation')]:
        target = root/'usr/share'/directory/name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SOURCE/'rotation'/name, target)


if __name__ == '__main__':
    main()
