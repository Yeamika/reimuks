#!/usr/bin/env python3
"""Local, unprivileged Debian ARM64 assembly. No host package installation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
BUILD = REPO / 'build'
TOOLS = BUILD / 'tools/root'
PROXY = 'http://10.0.0.1:18080'
MIRROR = 'https://ftp.debian.org/debian'
PYTHON = sys.executable


def run(args, **kw):
    print('+', ' '.join(map(str, args)), flush=True)
    return subprocess.run(list(map(str, args)), check=True, **kw)


def write(path, content, mode=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    if mode:
        path.chmod(mode)


def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def apt_state(name, arch, suite='trixie'):
    state = BUILD / name
    for d in ('lists/partial', 'archives/partial', 'empty-parts'):
        (state / d).mkdir(parents=True, exist_ok=True)
    (state / 'status').touch()
    key = TOOLS / 'usr/share/keyrings/debian-archive-keyring.gpg'
    write(state / 'sources.list', f'deb [signed-by={key}] {MIRROR} {suite} main\n')
    config = f'''Dir::State::status "{state}/status";
Dir::State::lists "{state}/lists";
Dir::Cache::archives "{state}/archives";
Dir::Etc::sourcelist "{state}/sources.list";
Dir::Etc::sourceparts "{state}/empty-parts";
Dir::Etc::parts "{state}/empty-parts";
Dir::Etc::main "-";
APT::Architecture "{arch}";
APT::Architectures {{ "{arch}"; }};
APT::Sandbox::User "{os.environ.get('USER', 'urn')}";
Acquire::http::Proxy "{PROXY}";
Acquire::https::Proxy "{PROXY}";
Acquire::Languages "none";
Acquire::Retries "3";
Acquire::https::Timeout "60";
APT::Get::List-Cleanup "false";
#clear APT::Update::Post-Invoke;
#clear APT::Update::Post-Invoke-Success;
#clear DPkg::Post-Invoke;
'''
    write(state / 'apt.conf', config)
    return state


def apt(state, *args, **kw):
    env = dict(os.environ, APT_CONFIG=str(state / 'apt.conf'))
    return run(['apt-get', *args], env=env, **kw)


def proot(root, command, bindings=()):
    args = [BUILD / 'tools/proot', '-0', '-r', root, '-w', '/',
            '-b', '/dev', '-b', '/proc', '-b', '/sys',
            '-q', TOOLS / 'usr/bin/qemu-aarch64']
    for binding in bindings:
        args += ['-b', binding]
    env = dict(os.environ, LC_ALL='C',
               DEBIAN_FRONTEND='noninteractive', PATH='/usr/sbin:/usr/bin:/sbin:/bin')
    return run(args + command, env=env)


def packages(profile):
    p = json.loads((REPO / 'profiles' / (f'desktop/{profile}.json' if profile in ('server', 'kde') else f'{profile}.json')).read_text())
    return list(dict.fromkeys((packages(p['extends']) if 'extends' in p else []) + p['packages']))


def prepare_tools():
    key = BUILD / 'tools/downloads/debian-archive-keyring.deb'
    if not (TOOLS / 'usr/share/keyrings/debian-archive-keyring.gpg').exists():
        key.parent.mkdir(parents=True, exist_ok=True)
        run(['curl', '--noproxy', '', '--proxy', PROXY, '-fL', '--retry', '3',
             '-o', key, MIRROR + '/pool/main/d/debian-archive-keyring/debian-archive-keyring_2025.1_all.deb'])
        if digest(key) != '9ea7778e443144ca490668737a8ab22dd3e748bb99e805e22ec055abeb3c7fac':
            raise SystemExit('Debian archive keyring bootstrap digest mismatch')
        run(['dpkg-deb', '-x', key, TOOLS])
    state = apt_state('apt-host', 'amd64')
    apt(state, 'update')
    apt(state, '--download-only', '--no-install-recommends', '-y', 'install', 'qemu-user')
    for deb in (state / 'archives').glob('*.deb'):
        run(['dpkg-deb', '-x', deb, TOOLS])
    # 5.1 lacks statx; 5.4 aborts on current systemd tmpfiles /proc operations.
    binary = BUILD / 'tools/proot'
    expected = 'db185300a9daabbce86aca7632d8c7fdc4249f6f153171954013b70c5f491ec0'
    if not binary.exists() or digest(binary) != expected:
        run(['curl', '--noproxy', '', '--proxy', PROXY, '-fL', '--retry', '3',
             '--max-time', '180', '-H', 'Accept: application/octet-stream', '-o', binary,
             'https://api.github.com/repos/proot-me/proot/releases/assets/606356115'])
    if digest(binary) != expected:
        raise SystemExit('PRoot v5.5.0 asset digest mismatch')
    binary.chmod(0o755)


def fetch(profile):
    state = apt_state(f'apt-{profile}', 'arm64')
    apt(state, 'update')
    apt(state, '--download-only', '--no-install-recommends', '-y', 'install',
        '?essential', *packages(profile))
    return state


def assemble(profile, state):
    root = BUILD / profile / 'rootfs'
    if root.exists():
        raise SystemExit(f'Refusing to overwrite {root}; resume via configure or use a fresh build directory.')
    root.mkdir(parents=True)
    seen = set()
    for deb in (state / 'archives').glob('*.deb'):
        name, _, arch = deb.name.split('_', 2)
        key = (name, arch)
        if key in seen:
            raise SystemExit(f'Multiple cached versions of {name}; use a fresh APT cache')
        seen.add(key)
    for name in ('bin', 'sbin', 'lib'):
        (root / 'usr' / name).mkdir(parents=True, exist_ok=True)
        (root / name).symlink_to('usr/' + name)
    for deb in sorted((state / 'archives').glob('*.deb')):
        run(['dpkg-deb', '-x', deb, root])
    for d in ('dev', 'proc', 'sys', 'run', 'tmp', 'work', 'var/lib/dpkg/updates',
              'var/lib/dpkg/info', 'var/lib/dpkg/triggers', 'var/lib/dpkg/alternatives'):
        (root / d).mkdir(parents=True, exist_ok=True)
    (root / 'tmp').chmod(0o1777)
    (root / 'var/lib/dpkg/status').touch()
    write(root / 'usr/sbin/policy-rc.d', '#!/bin/sh\nexit 101\n', 0o755)
    write(root / 'etc/hostname', f'reimuks-{profile}\n')
    write(root / 'etc/hosts', f'127.0.0.1 localhost\n127.0.1.1 reimuks-{profile}\n::1 localhost ip6-localhost\n')
    write(root / 'etc/apt/sources.list',
          'deb https://deb.debian.org/debian trixie main\n'
          'deb https://deb.debian.org/debian trixie-updates main\n'
          'deb https://security.debian.org/debian-security trixie-security main\n')
    write(root / 'etc/fstab', '# Root is mounted by REIMUKS initramfs. Add persistent mounts here.\n')
    write(root / 'etc/resolv.conf', Path('/etc/resolv.conf').read_text())
    return root


def configure(profile):
    root = BUILD / profile / 'rootfs'
    state = BUILD / f'apt-{profile}'
    target = json.loads((REPO / 'profiles' / (f'desktop/{profile}.json' if profile in ('server', 'kde') else f'{profile}.json')).read_text())['target']
    script = '''#!/bin/sh
set -eu
export DEBIAN_FRONTEND=noninteractive LC_ALL=C
# The initial extraction provides the programs needed by package preinst scripts.
# Re-unpack under target fakeroot so archive ownership and postinst chown survive.
set --
while IFS= read -r deb; do set -- "$@" "/packages/$deb"; done < /work/unpack-list
if [ "$#" -gt 0 ]; then dpkg --force-depends --unpack "$@"; fi
dpkg --configure -a
dpkg --audit > /work/dpkg-audit.txt
test ! -s /work/dpkg-audit.txt
id reimuks >/dev/null 2>&1 || adduser --disabled-password --gecos 'REIMUKS user' reimuks
usermod -a -G video,audio,input,render reimuks
passwd -l root
passwd -l reimuks
systemctl set-default TARGET
rm -f /usr/sbin/policy-rc.d /etc/machine-id /var/lib/dbus/machine-id
: > /etc/machine-id
rm -f /etc/resolv.conf
ln -s /run/systemd/resolve/stub-resolv.conf /etc/resolv.conf
dpkg-query -W -f='${Package}\\t${Version}\\t${Architecture}\\t${Status}\\n' > /work/packages.tsv
touch /work/configured
'''.replace('TARGET', target)
    # Credentials intentionally locked. The operator sets a password offline before deployment.
    work = BUILD / profile / 'work'
    ready = set()
    saved = work / 'fakeroot.state'
    if saved.exists():
        for block in (root / 'var/lib/dpkg/status').read_text().split('\n\n'):
            fields = dict(line.split(': ', 1) for line in block.splitlines() if ': ' in line and not line.startswith(' '))
            if fields.get('Status') in {'install ok '+s for s in ('installed', 'unpacked', 'half-configured', 'triggers-awaited', 'triggers-pending')}:
                ready.add(fields['Package'])
    pending = [p.name for p in sorted((state / 'archives').glob('*.deb'))
               if p.name.split('_', 1)[0] not in ready]
    write(work / 'unpack-list', ''.join(p+'\n' for p in pending))
    (work / 'configured').unlink(missing_ok=True)
    write(work / 'configure.sh', script, 0o755)
    restore = ['-i', '/work/fakeroot.state'] if saved.exists() else []
    proot(root, ['/usr/bin/fakeroot-tcp', *restore, '-s', '/work/fakeroot.state', '/bin/sh', '/work/configure.sh'],
          [f'{state}/archives:/packages', f'{work}:/work'])
    (work / 'configured').touch()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['tools', 'fetch', 'assemble', 'configure', 'password'])
    parser.add_argument('--profile', choices=['server', 'kde'], default='server')
    parser.add_argument('--user', choices=['root', 'reimuks'], default='reimuks', help='Account for the password action')
    args = parser.parse_args()
    (BUILD / 'logs').mkdir(parents=True, exist_ok=True)
    if args.action == 'tools':
        prepare_tools()
    elif args.action == 'fetch':
        fetch(args.profile)
    elif args.action == 'assemble':
        assemble(args.profile, BUILD / f'apt-{args.profile}')
    elif args.action == 'configure':
        configure(args.profile)
    else:
        root = BUILD / args.profile / 'rootfs'
        work = BUILD / args.profile / 'work'
        if not (work / 'configured').exists():
            raise SystemExit('Configure the rootfs before setting its login password')
        proot(root, ['/usr/bin/fakeroot-tcp', '-i', '/work/fakeroot.state',
                     '-s', '/work/fakeroot.state', '/usr/bin/passwd', args.user],
              [f'{work}:/work'])


if __name__ == '__main__':
    main()
