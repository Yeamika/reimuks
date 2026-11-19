#!/usr/bin/env python3
"""Provision a project-local Debian toolchain and EDK II BaseTools."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from output_paths import shared_root

ROOT = Path(__file__).resolve().parents[1]
BUILD = shared_root()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--proxy', default=os.environ.get('REIMUKS_DOWNLOAD_PROXY'))
    p.add_argument('--config', type=Path, default=ROOT/'config/build-tools.json')
    p.add_argument('--offline', action='store_true', help='reuse an existing compiler and Rust toolchain without downloading')
    p.add_argument('--rust-dist-server', default='https://static.rust-lang.org')
    p.add_argument('--edk2', type=Path, default=ROOT/'devices/w202ds/boot/components/edk2-ums9620/edk2')
    a = p.parse_args()
    settings = json.loads(a.config.read_text())
    def run(*argv, env=None):
        subprocess.run([str(x) for x in argv],check=True,env=env)
    state = BUILD/'apt-boot-tools'
    for name in ['archives/partial','lists/partial','empty-parts']:
        (state/name).mkdir(parents=True,exist_ok=True)
    (state/'status').touch()
    mirror = settings.get('host_mirror', 'https://deb.debian.org/debian')
    key = BUILD/'tools/root/usr/share/keyrings/debian-archive-keyring.gpg'
    signature = f' [signed-by={key}]' if key.is_file() else ''
    (state/'sources.list').write_text('deb'+signature+' '+mirror+' '+settings['host_suite']+' main\n')
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
    compiler = BUILD/'compiler/root'
    if a.offline:
        if not (compiler/'usr/bin/aarch64-linux-gnu-gcc').exists():
            p.error('offline mode requires the existing compiler/root toolchain')
        if not (BUILD/'rustup/toolchains'/(settings['rust_toolchain']+'-x86_64-unknown-linux-gnu')).is_dir():
            p.error('offline mode requires the configured Rust toolchain')
    else:
        run('apt-get','-c',config,'update')
        run('apt-get','-c',config,'--download-only','--no-install-recommends','-y','install',
            *settings['packages'])
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
    host_path = '/usr/local/bin:/usr/bin:/bin'
    def host_tool(name):
        return shutil.which(name, path=host_path)
    link('make', host_tool('make') or compiler/'usr/bin/make')
    def versioned(prefix):
        matches = [p for p in (compiler/'usr/bin').glob(prefix+'-*')
                   if p.name[len(prefix) + 1:].isdigit()]
        if not matches:
            raise SystemExit('Missing compiler: '+prefix)
        return max(matches, key=lambda p: int(p.name.rsplit('-', 1)[-1]))
    commands = {}
    host_libs = BUILD/'boot-tools/host-libs'
    host_libs.mkdir(parents=True, exist_ok=True)
    uuid = next((path for path in (
        Path('/usr/lib/x86_64-linux-gnu/libuuid.so.1'),
        Path('/lib/x86_64-linux-gnu/libuuid.so.1'),
    ) if path.is_file()), None)
    if uuid is not None:
        dest = host_libs/'libuuid.so'
        if dest.is_symlink() or dest.exists():
            dest.unlink()
        dest.symlink_to(uuid)
    loader = next((path for path in (
        compiler/'lib/x86_64-linux-gnu/ld-linux-x86-64.so.2',
        compiler/'usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2',
    ) if path.is_file()), None)
    if loader is None:
        raise SystemExit('Missing dynamic loader in compiler/root')
    libraries = str(compiler/'usr/lib/x86_64-linux-gnu')+':'+str(compiler/'lib/x86_64-linux-gnu')
    backend = BUILD/'boot-tools/cross-runtime'
    backend.mkdir(parents=True, exist_ok=True)
    cross_version = versioned('aarch64-linux-gnu-gcc').name.rsplit('-', 1)[-1]
    gcc_lib = compiler/'usr/lib/gcc-cross/aarch64-linux-gnu'/cross_version
    def wrapper(path, content):
        temporary = path.with_name(path.name+'.tmp')
        temporary.write_text(content)
        temporary.chmod(0o755)
        temporary.replace(path)
    # GCC's LTO plugin launches lto-wrapper, which in turn launches GCC/lto1.
    # -wrapper alone misses those nested execs. Give GCC executable shims via
    # -B and retain the public GCC wrapper as argv[0] for COLLECT_GCC.
    for name in ('cc1', 'cc1plus', 'collect2', 'lto-wrapper', 'lto1', 'as', 'ld'):
        target = (compiler/'usr/aarch64-linux-gnu/bin'/name if name in ('as', 'ld')
                  else gcc_lib/name)
        if target.is_file():
            wrapper(backend/name, f'#!/bin/sh\nexec "{loader}" --library-path "{libraries}" "{target}" "$@"\n')
    for name, prefix in [('gcc','gcc'),('cc','gcc'),('g++','g++'),('c++','g++')]:
        # Build host programs against the running host's libc. Debian cross
        # tools may require a newer libc than the host; execute those below
        # with their own loader, without exporting that libc into host tools.
        native = host_tool(prefix)
        if not native:
            raise SystemExit('Missing native host compiler: '+prefix)
        commands[name] = (Path(native), '-B"'+str(Path(native).parent)+'/" '
                          f'-idirafter "{compiler}/usr/include" -L"{host_libs}"')
    commands.update({name:(compiler/'usr/bin'/name,'') for name in ['ar','ld','objcopy','objdump','nm','ranlib','strip','pkg-config','msgfmt','xsltproc','ninja']})
    commands.update({name:(compiler/'usr'/('sbin' if name.endswith('.fat') else 'bin')/name, '')
                     for name in ['mkfs.fat','fsck.fat','mcopy','mtype']})
    for target in (compiler/'usr/bin').glob('aarch64-linux-gnu-*'):
        original_name = target.name
        extra = ''
        suffix = target.name.removeprefix('aarch64-linux-gnu-')
        driver = suffix in ('gcc', 'g++', 'cpp') or any(
            suffix.startswith(prefix+'-') and suffix[len(prefix)+1:].isdigit()
            for prefix in ('gcc', 'g++', 'cpp'))
        if driver:
            extra = f'-B"{backend}/" -B"{compiler}/usr/aarch64-linux-gnu/bin/" -B"{gcc_lib}/"'
        # gcc-ar/nm/ranlib otherwise exec an unwrapped binutils helper,
        # losing the private loader's library search path. Invoke the same
        # helper with GCC's LTO plugin through the regular loader wrapper.
        lto_tool = next((name for name in ('ar', 'nm', 'ranlib')
                        if suffix == 'gcc-'+name or
                        suffix.startswith('gcc-'+name+'-') and
                        suffix[len('gcc-'+name)+1:].isdigit()), None)
        if lto_tool:
            target = compiler/'usr/bin'/('aarch64-linux-gnu-'+lto_tool)
            extra = f'--plugin="{gcc_lib}/liblto_plugin.so"'
        commands[original_name]=(target,extra)
    for name,(target,extra) in commands.items():
        file=bin/name
        if file.is_symlink():
            file.unlink()
        if target.is_relative_to(compiler):
            suffix = name.removeprefix('aarch64-linux-gnu-')
            gcc_driver = suffix in ('gcc', 'g++', 'cpp') or any(
                suffix.startswith(prefix+'-') and suffix[len(prefix)+1:].isdigit()
                for prefix in ('gcc', 'g++', 'cpp'))
            argv0 = '--argv0 "$0" ' if gcc_driver else ''
            command = f'"{loader}" --library-path "{libraries}" {argv0}"{target}"'
        else:
            command = f'"{target}"'
        wrapper(file, f'#!/bin/sh\nexec {command} {extra} "$@"\n')
    env = dict(os.environ,PATH=str(bin)+':'+os.environ['PATH'],
               RUSTUP_HOME=str(BUILD/'rustup'),CARGO_HOME=str(BUILD/'cargo'),
               RUSTUP_DIST_SERVER=a.rust_dist_server)
    if a.proxy:
        env.update(HTTP_PROXY=a.proxy, HTTPS_PROXY=a.proxy)
    if not shutil.which('rustup'):
        raise SystemExit('rustup is required; install the official rustup launcher before provisioning')
    if not a.offline:
        run('rustup','toolchain','install',settings['rust_toolchain'],'--profile','minimal','--component','rust-src',
            '--target','aarch64-unknown-none',env=env)
    run('rustup', 'default', settings['rust_toolchain'], env=env)
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
                   TMPDIR=str(BUILD/'tmp'),
                   )
    if a.proxy:
        exports.update(HTTP_PROXY=a.proxy, HTTPS_PROXY=a.proxy,
                       GIT_CONFIG_COUNT='1', GIT_CONFIG_KEY_0='http.proxy', GIT_CONFIG_VALUE_0=a.proxy)
    (BUILD/'tmp').mkdir(exist_ok=True)
    (BUILD/'boot-tools/env.sh').write_text(''.join('export '+k+'='+shlex.quote(v)+'\n' for k,v in exports.items()))
    print('Source '+str(BUILD/'boot-tools/env.sh')+' before running reimuks.py')


if __name__ == '__main__':
    main()
