#!/usr/bin/env python3
"""Provision a project-local Debian toolchain and EDK II BaseTools."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT/'build'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--proxy', default=os.environ.get('REIMUKS_DOWNLOAD_PROXY'))
    p.add_argument('--config', type=Path, default=ROOT/'config/build-tools.json')
    p.add_argument('--rust-dist-server', default='https://static.rust-lang.org')
    p.add_argument('--edk2', type=Path, default=ROOT/'devices/w202ds/boot/pocketjs4edk2_uefi/components/edk2-ums9620/edk2')
    a = p.parse_args()
    settings = json.loads(a.config.read_text())
    def run(*argv, env=None):
        subprocess.run([str(x) for x in argv],check=True,env=env)
    state = BUILD/'apt-boot-tools'
    for name in ['archives/partial','lists/partial','empty-parts']:
        (state/name).mkdir(parents=True,exist_ok=True)
    (state/'status').touch()
    (state/'sources.list').write_text('deb https://ftp.debian.org/debian '+settings['host_suite']+' main\n')
    config = state/'apt.conf'
    config.write_text(f'''Dir::State::status "{state}/status";
Dir::State::lists "{state}/lists";
Dir::Cache::archives "{state}/archives";
Dir::Etc::sourcelist "{state}/sources.list";
Dir::Etc::sourceparts "{state}/empty-parts";
Dir::Etc::parts "{state}/empty-parts";
Dir::Etc::main "-";
APT::Architecture "{settings['host_architecture']}";
APT::Architectures {{ "{settings['host_architecture']}"; }};
{f'Acquire::http::Proxy "{a.proxy}";' if a.proxy else ''}
{f'Acquire::https::Proxy "{a.proxy}";' if a.proxy else ''}
Acquire::Languages "none";
Acquire::Retries "3";
#clear APT::Update::Post-Invoke;
#clear APT::Update::Post-Invoke-Success;
#clear DPkg::Post-Invoke;
''')
    run('apt-get','-c',config,'update')
    run('apt-get','-c',config,'--download-only','--no-install-recommends','-y','install',
        *settings['packages'])
    compiler = BUILD/'compiler/root'
    for deb in sorted((state/'archives').glob('*.deb')):
        run('dpkg-deb','-x',deb,compiler)
    runtime = BUILD/'compiler/runtime'
    runtime.mkdir(parents=True,exist_ok=True)
    skip = ('libc.','libm.','libpthread.','libdl.','librt.','ld-', 'libresolv.',
            'libnss_','libutil.','libanl.','libBrokenLocale.','libthread_db.')
    for source in (compiler/'usr/lib/x86_64-linux-gnu').glob('*.so*'):
        dest = runtime/source.name
        if not source.name.startswith(skip) and not dest.exists() and not dest.is_symlink():
            dest.symlink_to(source)
    bin = BUILD/'boot-tools/bin'
    bin.mkdir(parents=True,exist_ok=True)
    def link(name, target):
        dest = bin/name
        if dest.is_symlink() and dest.resolve() == Path(target).resolve(): return
        if dest.exists() or dest.is_symlink(): dest.unlink()
        dest.symlink_to(target)
    for name in ['python','python3']:
        link(name,Path(sys.executable).resolve())
    link('make',compiler/'usr/bin/make')
    def versioned(prefix):
        matches = [p for p in (compiler/'usr/bin').glob(prefix+'-*')
                   if p.name.rsplit('-', 1)[-1].isdigit()]
        if not matches:
            raise SystemExit('Missing compiler: '+prefix)
        return max(matches, key=lambda p: int(p.name.rsplit('-', 1)[-1]))
    commands = {}
    for name, prefix in [('gcc','gcc'),('cc','gcc'),('g++','g++'),('c++','g++')]:
        commands[name] = (versioned(prefix), f'--sysroot="{compiler}" -B"{compiler}/usr/bin/"')
    commands.update({name:(compiler/'usr/bin'/name,'') for name in ['ar','ld','objcopy','objdump','nm','ranlib','strip','pkg-config','msgfmt','xsltproc','ninja']})
    commands.update({name:(compiler/'usr'/('sbin' if name.endswith('.fat') else 'bin')/name, '')
                     for name in ['mkfs.fat','fsck.fat','mcopy','mtype']})
    for target in (compiler/'usr/bin').glob('aarch64-linux-gnu-*'):
        extra = ''
        if target.name.removeprefix('aarch64-linux-gnu-').split('-')[0] in ('gcc', 'g++', 'cpp'):
            version = versioned('aarch64-linux-gnu-gcc').name.rsplit('-', 1)[-1]
            extra = f'-B"{compiler}/usr/aarch64-linux-gnu/bin/" -B"{compiler}/usr/lib/gcc-cross/aarch64-linux-gnu/{version}/"'
        commands[target.name]=(target,extra)
    for name,(target,extra) in commands.items():
        file=bin/name
        file.write_text(f'#!/bin/sh\nexport LD_LIBRARY_PATH="{runtime}${{LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}}"\nexec "{target}" {extra} "$@"\n')
        file.chmod(0o755)
    env = dict(os.environ,PATH=str(bin)+':'+os.environ['PATH'],
               RUSTUP_HOME=str(BUILD/'rustup'),CARGO_HOME=str(BUILD/'cargo'),
               RUSTUP_DIST_SERVER=a.rust_dist_server)
    if a.proxy:
        env.update(HTTP_PROXY=a.proxy, HTTPS_PROXY=a.proxy)
    if not shutil.which('rustup'):
        raise SystemExit('rustup is required; install the official rustup launcher before provisioning')
    run('rustup','toolchain','install',settings['rust_toolchain'],'--profile','minimal','--component','rust-src',
        '--target','aarch64-unknown-none',env=env)
    tools=BUILD/'boot-tools/basetools'
    if not tools.exists():
        platform=a.edk2.resolve().parent
        run('bash',platform/'build-tools.sh','--edk2',a.edk2.resolve(),'--output',tools,env=env)
    else:
        run('make','-C',tools,'-j4',env=env)
    # This file is sourced explicitly by the caller; no system configuration changes.
    import shlex
    exports = dict(PATH=str(bin)+':'+os.environ['PATH'],EDK_TOOLS_PATH=str(tools),
                   RUSTUP_HOME=env['RUSTUP_HOME'],CARGO_HOME=env['CARGO_HOME'],
                   CARGO_TARGET_DIR=str(BUILD/'boot-cargo-target'),TMPDIR=str(BUILD/'tmp'),
                   )
    if a.proxy:
        exports.update(HTTP_PROXY=a.proxy, HTTPS_PROXY=a.proxy,
                       GIT_CONFIG_COUNT='1', GIT_CONFIG_KEY_0='http.proxy', GIT_CONFIG_VALUE_0=a.proxy)
    (BUILD/'tmp').mkdir(exist_ok=True)
    (BUILD/'boot-tools/env.sh').write_text(''.join('export '+k+'='+shlex.quote(v)+'\n' for k,v in exports.items()))
    print('Source '+str(BUILD/'boot-tools/env.sh')+' before running reimuks.py')


if __name__ == '__main__':
    main()
