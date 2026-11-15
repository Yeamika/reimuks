#!/usr/bin/env python3
"""Prepare a target SDK from authenticated distro packages without installing on the host."""
import argparse
import json
from pathlib import Path
import shlex
import subprocess
import build


def prepare(name, packages, output):
    if not name.replace('-', '_').isidentifier():
        raise ValueError('Invalid SDK name')
    state = build.apt_state('apt-'+name, build.DISTRIBUTION['architecture'])
    build.apt(state, 'update')
    # An empty planning cache gives the complete dependency closure, including
    # archives already cached by another build. Never extract unrelated packages.
    planning = state/'plan-archives'
    (planning/'partial').mkdir(parents=True, exist_ok=True)
    plan = build.apt(state, '-o', 'Dir::Cache::archives='+str(planning),
                     '--print-uris', '--download-only', '--no-install-recommends',
                     '-y', 'install', *packages, capture_output=True, text=True).stdout
    names = [shlex.split(line)[1] for line in plan.splitlines() if line.startswith("'")]
    if not names or any(Path(name).name != name for name in names):
        raise ValueError('Invalid or empty SDK package closure')
    build.apt(state, '--download-only', '--no-install-recommends', '-y', 'install', *packages)
    archives = [state/'archives'/name for name in names]
    hashes = {p.name: build.digest(p) for p in archives}
    marker = output/'sdk.json'
    expected = {'distribution': build.identity(build.DISTRIBUTION),
                'packages': packages, 'archives': hashes}
    if marker.is_file() and json.loads(marker.read_text()) == expected:
        print('SDK is current: '+str(output))
        return
    root = output/'root'
    if root.exists():
        if not marker.is_file():
            raise ValueError('Refusing to replace an unrecognized SDK directory: '+str(root))
        import shutil
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    for archive in archives:
        subprocess.run(['dpkg-deb', '-x', str(archive), str(root)], check=True)
    build.write(marker, json.dumps(expected, indent=2)+'\n')
    print('SDK prepared: '+str(root))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name', required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--distribution', default=build.DISTRIBUTION['id'])
    parser.add_argument('--cc', default='aarch64-linux-gnu-gcc')
    parser.add_argument('--cxx', default='aarch64-linux-gnu-g++')
    parser.add_argument('packages', nargs='+')
    args = parser.parse_args()
    build.select_distribution(args.distribution)
    output = (args.output or build.BUILD/'sdk'/args.name).resolve()
    prepare(args.name, args.packages, output)
    root = output/'root'
    libraries = root/'usr/lib/aarch64-linux-gnu'
    pkgconfig = ['env', 'PKG_CONFIG_SYSROOT_DIR='+str(root),
                 'PKG_CONFIG_LIBDIR='+str(libraries/'pkgconfig')+':'+str(root/'usr/share/pkgconfig'),
                 'PKG_CONFIG_PATH=', 'pkg-config']
    flags = ['--sysroot='+str(root)]
    build.write(output/'arm64.ini', '\n'.join([
        '[binaries]', 'c = '+repr(shlex.split(args.cc)),
        'cpp = '+repr(shlex.split(args.cxx)), "ar = 'aarch64-linux-gnu-ar'",
        "strip = 'aarch64-linux-gnu-strip'", 'pkg-config = '+repr(pkgconfig),
        '[host_machine]', "system = 'linux'", "cpu_family = 'aarch64'",
        "cpu = 'aarch64'", "endian = 'little'", '[properties]',
        'sys_root = '+repr(str(root)), 'needs_exe_wrapper = true',
        '[built-in options]', 'c_args = '+repr(flags), 'cpp_args = '+repr(flags),
        'c_link_args = '+repr(flags+['-Wl,-rpath-link,'+str(libraries)]),
        'cpp_link_args = '+repr(flags+['-Wl,-rpath-link,'+str(libraries)]), '',
    ]))


if __name__ == '__main__':
    main()
