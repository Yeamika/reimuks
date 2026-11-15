#!/usr/bin/env python3
"""Build a board's kernel/modules through its own public build entry."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def tool_environment():
    env = dict(os.environ)
    cache = ROOT / 'build'
    compiler = cache / 'compiler'
    host = cache / 'tools/host'
    bins = [host / 'bin', host / 'usr/bin', host / 'sbin',
            cache / 'boot-tools/bin', cache / 'tools/native/bin', compiler / 'root/usr/bin']
    env['PATH'] = os.pathsep.join(str(p) for p in bins if p.is_dir()) + os.pathsep + env.get('PATH', '')
    libraries = [compiler / 'runtime', host / 'lib/x86_64-linux-gnu', host / 'usr/lib/x86_64-linux-gnu']
    env['LD_LIBRARY_PATH'] = os.pathsep.join(str(p) for p in libraries if p.is_dir())
    gccs = [p for p in (compiler / 'root/usr/bin').glob('x86_64-linux-gnu-gcc-*')
            if p.name.rsplit('-', 1)[-1].isdigit()]
    if gccs:
        gcc = sorted(gccs)[-1]
        version = gcc.name.rsplit('-', 1)[-1]
        prefix = compiler / 'root'
        env['HOSTCC'] = f'{gcc} --sysroot={prefix} -B{prefix}/usr/bin/ -B{prefix}/usr/lib/gcc/x86_64-linux-gnu/{version}/'
    if host.is_dir():
        env['HOSTCFLAGS'] = f'-O2 -I{host}/usr/include -I{host}/usr/include/x86_64-linux-gnu'
        env['HOSTLDFLAGS'] = f'-L{host}/usr/lib/x86_64-linux-gnu'
        env['BISON_PKGDATADIR'] = str(host / 'usr/share/bison')
        env['M4'] = str(host / 'usr/bin/m4')
    perl_paths = [p for p in (compiler / 'root/usr/lib').glob('*/perl-base') if p.is_dir()]
    if perl_paths:
        env['PERL5LIB'] = os.pathsep.join(map(str, perl_paths))
    return env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--board', required=True)
    parser.add_argument('--profile', default='desktop')
    parser.add_argument('--jobs', type=int, default=4)
    args = parser.parse_args()
    board = ROOT / 'devices' / args.board
    if Path(args.board).name != args.board or args.jobs < 1:
        parser.error('Invalid board or job count')
    config = json.loads((board / 'board.json').read_text())
    reference = Path(config['kernel_builder'])
    if reference.is_absolute() or '..' in reference.parts:
        parser.error('Invalid board kernel builder')
    builder = (board / reference).resolve()
    source = (board / config.get('kernel_source', 'kernel')).resolve()
    if not builder.is_relative_to(source):
        parser.error('Kernel builder must belong to its source project')
    if not args.profile.isidentifier():
        parser.error('Invalid kernel profile')
    subprocess.run([sys.executable, str(builder), '--profile', args.profile,
                    '--kernel-out', str(source / 'output' / ('kernel-' + args.profile)),
                    '--jobs', str(args.jobs), 'all'], cwd=source,
                   env=tool_environment(), check=True)


if __name__ == '__main__':
    main()
