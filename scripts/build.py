#!/usr/bin/env python3
"""Local, unprivileged Debian ARM64 assembly. No host package installation."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
from distributions import DEFAULT, load_distribution, identity, resolve_profile, sources_list, additional_repositories, repository_key, check_os_release, check_package_versions
from accounts import load_accounts, password_operations, DEFAULT_CONFIG

REPO = Path(__file__).resolve().parents[1]
BUILD = REPO / 'build'
TOOLS = BUILD / 'tools/root'
PROXY = os.environ.get('REIMUKS_DOWNLOAD_PROXY')
MIRROR = 'https://ftp.debian.org/debian'
PYTHON = sys.executable
DISTRIBUTION = load_distribution(os.environ.get('REIMUKS_DISTRIBUTION', DEFAULT))
BOARD = os.environ.get('REIMUKS_BOARD', 'w202ds')


def select_distribution(name):
    global DISTRIBUTION
    DISTRIBUTION = load_distribution(name)


def select_board(name):
    global BOARD
    if not name.isidentifier() or not (REPO/'devices'/name/'board.json').is_file():
        raise ValueError('Unknown board: '+name)
    BOARD = name


def board_directory():
    return REPO/'devices'/BOARD


def board_build():
    return BUILD if BOARD == 'w202ds' else BUILD/'boards'/BOARD


def kernel_directory():
    return board_build()/'kernel'


def distribution_build():
    # Preserve the existing Debian trixie artifacts and configured accounts.
    base = board_build()
    return base if DISTRIBUTION['id'] == DEFAULT else base/'distributions'/DISTRIBUTION['id']


def profile_directory(profile):
    return distribution_build()/profile.removeprefix('desktop/')


def artifact_directory():
    return distribution_build()/'artifacts'


def bind_distribution(directory, refresh_cache=False):
    marker = directory/'distribution.json'
    expected = identity(DISTRIBUTION)
    if marker.is_file() and json.loads(marker.read_text()) != expected:
        if not refresh_cache:
            raise ValueError(f'Distribution configuration changed; use a fresh rootfs: {directory}')
        # APT refreshes authenticated indexes before fetching. Keep reusable
        # archives when package selections change, but invalidate completion.
        (directory/'fetch-complete.json').unlink(missing_ok=True)
    write(marker, json.dumps(expected, indent=2)+'\n')


def check_rootfs(profile):
    directory = profile_directory(profile)
    check_os_release((directory/'rootfs/usr/lib/os-release').read_text(), DISTRIBUTION)
    bind_distribution(directory/'work')


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


def apt_state(name, arch):
    # Host tools use the fixed bootstrap distro, independently of the target.
    host = name == 'apt-host'
    distribution = load_distribution(DEFAULT) if host else DISTRIBUTION
    state = (BUILD if host else distribution_build()) / name
    for d in ('lists/partial', 'archives/partial', 'empty-parts'):
        (state / d).mkdir(parents=True, exist_ok=True)
    (state / 'status').touch()
    key = TOOLS / 'usr/share/keyrings/debian-archive-keyring.gpg'
    if not host:
        bind_distribution(state, refresh_cache=True)
    write(state / 'sources.list', sources_list(distribution, keyring=key, profile=name.removeprefix('apt-')))
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
{f'Acquire::http::Proxy "{PROXY}";' if PROXY else ''}
{f'Acquire::https::Proxy "{PROXY}";' if PROXY else ''}
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


def proot(root, command, bindings=(), **kwargs):
    args = [BUILD / 'tools/proot', '-0', '-r', root, '-w', '/',
            '-b', '/dev', '-b', '/proc',
            '-q', TOOLS / 'usr/bin/qemu-aarch64']
    for binding in bindings:
        args += ['-b', binding]
    env = {key: value for key, value in os.environ.items()
           if not key.startswith('XDG_') and key not in ('QT_PLUGIN_PATH', 'QML2_IMPORT_PATH')}
    env.update(HOME='/root', USER='root', LOGNAME='root', LC_ALL='C', SYSTEMD_OFFLINE='1',
               DEBIAN_FRONTEND='noninteractive', PATH='/usr/sbin:/usr/bin:/sbin:/bin')
    return run(args + command, env=env, **kwargs)


def packages(profile):
    return resolve_profile(profile, DISTRIBUTION)['packages']


def prepare_tools():
    bootstrap = json.loads((REPO/'config/build-tools.json').read_text())['bootstrap']
    keyring = bootstrap['archive_keyring']
    key = BUILD / 'tools/downloads/debian-archive-keyring.deb'
    if not (TOOLS / 'usr/share/keyrings/debian-archive-keyring.gpg').exists():
        key.parent.mkdir(parents=True, exist_ok=True)
        run(['curl', *(['--noproxy', '', '--proxy', PROXY] if PROXY else []), '-fL', '--retry', '3',
             '-o', key, keyring['url']])
        if digest(key) != keyring['sha256']:
            raise SystemExit('Debian archive keyring bootstrap digest mismatch')
        run(['dpkg-deb', '-x', key, TOOLS])
    state = apt_state('apt-host', 'amd64')
    apt(state, 'update')
    apt(state, '--download-only', '--no-install-recommends', '-y', 'install', 'qemu-user')
    for deb in (state / 'archives').glob('*.deb'):
        run(['dpkg-deb', '-x', deb, TOOLS])
    # 5.1 lacks statx; 5.4 aborts on current systemd tmpfiles /proc operations.
    binary = BUILD / 'tools/proot'
    expected = bootstrap['proot']['sha256']
    if not binary.exists() or digest(binary) != expected:
        run(['curl', *(['--noproxy', '', '--proxy', PROXY] if PROXY else []), '-fL', '--retry', '3',
             '--max-time', '180', '-H', 'Accept: application/octet-stream', '-o', binary,
             bootstrap['proot']['url']])
    if digest(binary) != expected:
        raise SystemExit('PRoot bootstrap digest mismatch')
    binary.chmod(0o755)


def fetch(profile):
    state = apt_state(f'apt-{profile}', DISTRIBUTION['architecture'])
    receipt = state/'fetch-complete.json'
    receipt.unlink(missing_ok=True)
    apt(state, 'update')
    specification = resolve_profile(profile, DISTRIBUTION)
    versions = {}
    for package in specification.get('minimum_package_versions', {}):
        policy = subprocess.run(['apt-cache', 'policy', package],
                                env=dict(os.environ, APT_CONFIG=str(state / 'apt.conf'), LC_ALL='C'),
                                capture_output=True, text=True, check=True).stdout
        for line in policy.splitlines():
            if line.strip().startswith('Candidate:'):
                versions[package] = line.split(':', 1)[1].strip()
    check_package_versions(specification, versions)
    apt(state, '--download-only', '--install-recommends' if specification['install_recommends'] else '--no-install-recommends', '-y', 'install',
        '?essential', *packages(profile))
    write(receipt, json.dumps({
        'distribution': identity(DISTRIBUTION), 'profile': specification,
        'archives': {p.name: digest(p) for p in sorted((state/'archives').glob('*.deb'))}
    }, indent=2)+'\n')
    return state


def cached_packages(state):
    candidates = {}
    for archive in sorted((state / 'archives').glob('*.deb')):
        package, version, architecture = subprocess.check_output(
            ['dpkg-deb', '-f', str(archive), 'Package', 'Version', 'Architecture'], text=True).splitlines()
        # Multiple fields are printed with labels by dpkg-deb.
        package, version, architecture = [value.split(': ', 1)[-1] for value in (package, version, architecture)]
        key = (package, architecture)
        previous = candidates.get(key)
        if previous is None or subprocess.run(
                ['dpkg', '--compare-versions', version, 'gt', previous[0]], check=False).returncode == 0:
            candidates[key] = (version, archive)
    return candidates


def assemble(profile, state):
    os.umask(0o022)
    receipt = state/'fetch-complete.json'
    if not receipt.is_file():
        raise SystemExit('Package fetch is incomplete; run fetch for this profile before assemble.')
    downloaded = json.loads(receipt.read_text())
    if (downloaded['distribution'] != identity(DISTRIBUTION) or
            downloaded['profile'] != resolve_profile(profile, DISTRIBUTION)):
        raise SystemExit('Package selection changed; run fetch again before assemble.')
    for name, expected in downloaded['archives'].items():
        archive = state/'archives'/name
        if Path(name).name != name or not archive.is_file() or digest(archive) != expected:
            raise SystemExit('Downloaded package changed or is missing: '+name+'; run fetch again.')
    if set(downloaded['archives']) != {p.name for p in (state/'archives').glob('*.deb')}:
        raise SystemExit('Package cache changed; run fetch again before assemble.')
    root = profile_directory(profile) / 'rootfs'
    if root.exists():
        raise SystemExit(f'Refusing to overwrite {root}; resume via configure or use a fresh build directory.')
    work = profile_directory(profile)/'work'
    if work.is_symlink():
        raise ValueError('Rootfs work directory must not be a symlink')
    if work.exists():
        shutil.rmtree(work)
    root.mkdir(parents=True)
    bind_distribution(profile_directory(profile)/'work')
    candidates = cached_packages(state)
    for name in ('bin', 'sbin', 'lib'):
        (root / 'usr' / name).mkdir(parents=True, exist_ok=True)
        (root / name).symlink_to('usr/' + name)
    for _, deb in sorted(candidates.values(), key=lambda item: item[1].name):
        run(['dpkg-deb', '-x', deb, root])
    for d in ('dev', 'proc', 'sys', 'run', 'tmp', 'work', 'var/lib/dpkg/updates',
              'var/lib/dpkg/info', 'var/lib/dpkg/triggers', 'var/lib/dpkg/alternatives'):
        (root / d).mkdir(parents=True, exist_ok=True)
    (root / 'tmp').chmod(0o1777)
    (root / 'var/lib/dpkg/status').touch()
    write(root / 'usr/sbin/policy-rc.d', '#!/bin/sh\nexit 101\n', 0o755)
    write(root / 'etc/hostname', f'reimuks-{profile}\n')
    write(root / 'etc/hosts', f'127.0.0.1 localhost\n127.0.1.1 reimuks-{profile}\n::1 localhost ip6-localhost\n')
    write(root / 'etc/apt/sources.list', sources_list(DISTRIBUTION, target=True, profile=profile))
    for source in additional_repositories(DISTRIBUTION, profile):
        destination = root/source['target_keyring'].lstrip('/')
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(repository_key(DISTRIBUTION, source), destination)

    write(root / 'etc/fstab', '# Root is mounted by REIMUKS initramfs. Add persistent mounts here.\n')
    write(root / 'etc/resolv.conf', Path('/etc/resolv.conf').read_text())
    write(work/'clean-rootfs-v1', '1\n')
    return root


def apply_accounts(profile, accounts=None):
    policy = load_accounts(accounts)
    check_rootfs(profile)
    root = profile_directory(profile) / 'rootfs'
    work = profile_directory(profile) / 'work'
    restore = ['-i', '/work/fakeroot.state'] if (work/'fakeroot.state').exists() else []
    for command, secret_input in password_operations(policy):
        proot(root, ['/usr/bin/fakeroot-tcp', *restore, '-s', '/work/fakeroot.state', *command],
              [f'{work}:/work'], input=secret_input, text=True)


def configure_locale(profile, root):
    locale = resolve_profile(profile, DISTRIBUTION).get('locale', 'C.UTF-8')
    if locale != 'C.UTF-8':
        if not re.fullmatch(r'[a-z]{2}_[A-Z]{2}\.UTF-8', locale):
            raise ValueError('Unsupported profile locale')
        proot(root, ['/usr/bin/localedef', '-i', locale.split('.')[0],
                     '-f', 'UTF-8', locale], timeout=180)
    write(root/'etc/default/locale', 'LANG='+locale+'\n')


def configure_display(profile, root):
    specification = resolve_profile(profile, DISTRIBUTION)
    if specification.get('display_protocol') != 'wayland':
        return
    if specification.get('display_manager') == 'sddm':
        # SDDM and the desktop both use DRM/Wayland, including the greeter.
        write(root / 'etc/sddm.conf.d/20-reimuks-wayland.conf',
              '[General]\nDisplayServer=wayland\n\n'
              '[Wayland]\nCompositorCommand=kwin_wayland --drm --no-lockscreen --no-global-shortcuts --locale1\n'
              'SessionDir=/usr/share/wayland-sessions\n\n'
              '[X11]\nSessionDir=/usr/share/reimuks/disabled-xsessions\n')
        # Debian's service explicitly passes --xwayland. Reset ExecStart so
        # KWin never starts the compatibility server in this profile.
        write(root / 'etc/systemd/user/plasma-kwin_wayland.service.d/20-reimuks-wayland.conf',
              '[Service]\nExecStart=\nExecStart=/usr/bin/kwin_wayland_wrapper\n')
    elif specification.get('display_manager') == 'gdm3':
        write(root / 'etc/gdm3/daemon.conf', '[daemon]\nWaylandEnable=true\n')


def configure(profile, accounts=None):
    os.umask(0o022)
    accounts = accounts if accounts is not None else DEFAULT_CONFIG
    load_accounts(accounts)  # Never discover private credentials implicitly during base setup.
    check_rootfs(profile)
    root = profile_directory(profile) / 'rootfs'
    state = distribution_build() / f'apt-{profile}'
    target = resolve_profile(profile, DISTRIBUTION)['target']
    script = '''#!/bin/sh
set -eu
umask 022
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
'''.replace('TARGET', target)
    work = profile_directory(profile) / 'work'
    ready = {}
    saved = work / 'fakeroot.state'
    if saved.exists():
        for block in (root / 'var/lib/dpkg/status').read_text().split('\n\n'):
            fields = dict(line.split(': ', 1) for line in block.splitlines() if ': ' in line and not line.startswith(' '))
            if fields.get('Status') in ('install ok installed', 'install ok unpacked',
                                         'install ok half-configured', 'install ok triggers-awaited',
                                         'install ok triggers-pending'):
                ready[fields['Package']] = fields.get('Version')
    candidates = cached_packages(state)
    pending = [archive.name for (package, _), (version, archive) in sorted(candidates.items())
               if ready.get(package) != version]
    write(work / 'unpack-list', ''.join(p+'\n' for p in pending))
    (work / 'configured').unlink(missing_ok=True)
    write(work / 'configure.sh', script, 0o755)
    restore = ['-i', '/work/fakeroot.state'] if saved.exists() else []
    proot(root, ['/usr/bin/fakeroot-tcp', *restore, '-s', '/work/fakeroot.state', '/bin/sh', '/work/configure.sh'],
          [f'{state}/archives:/packages', f'{work}:/work'])
    configure_display(profile, root)
    from acceleration import install as install_acceleration
    install_acceleration(root, profile, DISTRIBUTION)
    apply_accounts(profile, accounts)
    (work / 'configured').touch()


def main():
    os.umask(0o022)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['tools', 'fetch', 'assemble', 'configure', 'accounts', 'password'])
    parser.add_argument('--profile', choices=['server', 'kde', 'gnome'], default='server')
    parser.add_argument('--board', default=os.environ.get('REIMUKS_BOARD', 'w202ds'))
    parser.add_argument('--distribution', default=os.environ.get('REIMUKS_DISTRIBUTION', DEFAULT))
    parser.add_argument('--user', choices=['root', 'reimuks'], default='reimuks', help='Account for the password action')
    parser.add_argument('--accounts', type=Path, help='Desktop account configuration; defaults to config/accounts.local.json when present')
    args = parser.parse_args()
    if args.accounts is not None and args.action not in ('configure', 'accounts'):
        parser.error('--accounts applies only to configure and accounts')
    select_board(args.board)
    select_distribution(args.distribution)
    (BUILD / 'logs').mkdir(parents=True, exist_ok=True)
    if args.action == 'tools':
        prepare_tools()
    elif args.action == 'fetch':
        fetch(args.profile)
    elif args.action == 'assemble':
        assemble(args.profile, distribution_build() / f'apt-{args.profile}')
    elif args.action == 'configure':
        configure(args.profile, args.accounts)
    elif args.action == 'accounts':
        check_rootfs(args.profile)
        if not (profile_directory(args.profile)/'work/configured').exists():
            raise SystemExit('Configure the rootfs before applying its account policy')
        apply_accounts(args.profile, args.accounts)
    else:
        check_rootfs(args.profile)
        root = profile_directory(args.profile) / 'rootfs'
        work = profile_directory(args.profile) / 'work'
        if not (work / 'configured').exists():
            raise SystemExit('Configure the rootfs before setting its login password')
        proot(root, ['/usr/bin/fakeroot-tcp', '-i', '/work/fakeroot.state',
                     '-s', '/work/fakeroot.state', '/usr/bin/passwd', args.user],
              [f'{work}:/work'])


if __name__ == '__main__':
    main()
