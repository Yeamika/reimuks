#!/usr/bin/env python3
"""Build independently managed distro, desktop and board integration packages."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tarfile
import tempfile

import build
from board_exports import relative_path
from board_userspace import install_rootfs, prepare_rootfs, policy_layers
from distributions import identity, resolve_profile, check_os_release
from apt_selection import selected_archives
from tree_cleanup import remove_tree
from user_overlay import archive


def profile_name(profile):
    profile = profile.removeprefix('desktop/')
    if profile not in ('server', 'kde', 'gnome'):
        raise ValueError('Unsupported layer profile')
    return profile


def desktop_plan(profile, distribution=None):
    profile = profile_name(profile)
    distribution = distribution or build.DISTRIBUTION
    if profile == 'server':
        return []
    common = distribution.get('desktop_common', {})
    if not common:
        raise ValueError('Distribution has no common desktop package definition')
    mapping = distribution['profiles']['desktop/'+profile]
    return [dict(kind='de-common', package='reimuks-de-common', depends=common['packages']),
            dict(kind='de-'+profile, package='reimuks-de-'+profile,
                 depends=list(dict.fromkeys(['reimuks-de-common', *mapping['packages'], *mapping['required_packages']])))]


def plan(profile, board=None, distribution=None):
    profile = profile_name(profile)
    board = board or build.board_directory()
    distribution = distribution or build.DISTRIBUTION
    config = json.loads((board/'rootfs/packages.json').read_text())
    if config.get('schema') != 1:
        raise ValueError('Unsupported board package schema')
    result = [dict(config['board'], kind='board')]
    if profile != 'server':
        desktop = desktop_plan(profile, distribution)
        result += [desktop[0], dict(config['board-de'], kind='board-de'), desktop[1]]
    result.append(dict(config['profiles'][profile], kind='board-'+profile))
    for entry in result:
        if not re.fullmatch(r'[a-z0-9][a-z0-9+.-]+', entry['package']):
            raise ValueError('Invalid layer package name')
    return result


def package_tree(root, output, name, depends, kind, version=None, conflicts=(), replaces=()):
    """dpkg owns payload files; private state and kernel artifacts never belong here."""
    for path in root.rglob('*'):
        relative = path.relative_to(root)
        if ('__pycache__' in relative.parts or path.suffix in ('.pyc', '.pyo', '.ko') or
                relative.parts[:3] == ('usr', 'lib', 'modules') or
                relative.parts[:2] == ('home', 'reimuks') or
                str(relative) in ('etc/shadow', 'etc/passwd', 'etc/hostname')):
            raise ValueError('Non-package state in layer: '+str(relative))
    content = hashlib.sha256()
    conffiles = []
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root).as_posix()
        content.update(relative.encode()+b'\0')
        if path.is_symlink():
            content.update(b'L'+os.readlink(path).encode())
        elif path.is_file():
            content.update(b'F'+path.read_bytes())
            if relative.startswith('etc/'):
                conffiles.append('/'+relative)
        content.update(str(path.lstat().st_mode & 0o7777).encode())
    content.update(json.dumps(depends, sort_keys=True).encode())
    content.update(json.dumps([conflicts,replaces], sort_keys=True).encode())
    digest = content.hexdigest()
    version = version or '1.0+'+digest[:16]
    if not re.fullmatch(r'[0-9][a-zA-Z0-9.+:~\-]*', version):
        raise ValueError('Invalid Debian package version')
    control = root/'DEBIAN'
    control.mkdir(exist_ok=True)
    build.write(control/'control', f'Package: {name}\nVersion: {version}\n'
                f'Architecture: {build.DISTRIBUTION["architecture"]}\n'
                'Maintainer: REIMUKS maintainers\nSection: misc\nPriority: optional\n'
                + ('Depends: '+', '.join(dict.fromkeys(depends))+'\n' if depends else '')
                + ('Conflicts: '+', '.join(conflicts)+'\n' if conflicts else '')
                + ('Replaces: '+', '.join(replaces)+'\n' if replaces else '')
                + f'Description: REIMUKS {kind} integration\n')
    if conffiles:
        build.write(control/'conffiles', '\n'.join(conffiles)+'\n')
    output.mkdir(parents=True, exist_ok=True)
    destination = output/f'{name}.deb'
    partial = destination.with_suffix('.deb.part')
    subprocess.run(['dpkg-deb', '--root-owner-group', '-Zgzip', '-z6', '--build', str(root), str(partial)],
                   env=dict(os.environ, SOURCE_DATE_EPOCH=os.environ.get('SOURCE_DATE_EPOCH', '0')), check=True)
    partial.replace(destination)
    return {'kind':kind, 'package':name, 'version':version, 'depends':depends,
            'file':destination.name, 'sha256':build.digest(destination), 'payload_sha256':digest}


def prepare_inputs(root, context, specification):
    """Only declared distro templates are borrowed; none enter the board package."""
    paths = []
    for name in specification.get('preparer_inputs', []):
        source = relative_path(context, name)
        destination = relative_path(root, name)
        if destination.exists() or destination.is_symlink():
            raise ValueError('Preparer input conflicts with board payload: '+name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, destination, symlinks=True)
        else:
            shutil.copy2(source, destination)
        paths.append(destination)
    return paths


def pack_board(profile, context=None, output=None):
    profile = profile_name(profile)
    board = build.board_directory()
    output = output or build.artifact_directory()/'layers'
    work = build.distribution_build()/'layers/work'
    work.mkdir(parents=True, exist_ok=True)
    entries = plan(profile)
    result = []
    owned = {}
    with tempfile.TemporaryDirectory(dir=work) as tmp:
        for entry in entries:
            if 'selector' not in entry:
                continue
            root = Path(tmp)/entry['kind']
            root.mkdir()
            install_rootfs(root, profile, board, only=entry['selector'])
            # Upstream ModemManager policy belongs to the distro package. The
            # board supplies its private adapter and board-specific udev rules.
            for name in entry.get('omit', []):
                relative_path(root, name).unlink(missing_ok=True)
            if entry.get('preparer_inputs'):
                if context is None:
                    raise ValueError('Board desktop package requires a configured distro --context')
                borrowed = prepare_inputs(root, context, entry)
                prepare_rootfs(root, board, profile, only=entry['selector'])
                for path in reversed(borrowed):
                    if path.is_dir():
                        remove_tree(path)
                    else:
                        path.unlink()
                for path in sorted(root.rglob('*'), key=lambda p: len(p.parts), reverse=True):
                    if path.is_dir() and not path.is_symlink() and not any(path.iterdir()):
                        path.rmdir()
            # Fail rather than silently let a later .deb steal another layer's files.
            for path in root.rglob('*'):
                if not path.is_symlink() and path.is_dir():
                    continue
                name = path.relative_to(root).as_posix()
                if name in owned:
                    raise ValueError(f'Layer file collision: {name}: {owned[name]} / {entry["package"]}')
                owned[name] = entry['package']
            # Retire unowned legacy files and disable obsolete service links offline.
            cleanup = []
            for layer in policy_layers(board, profile, only=entry['selector']):
                cleanup += layer.get('remove', [])
                cleanup += ['etc/systemd/system/'+p for p in layer.get('disable', [])]
            if cleanup:
                control = root/'DEBIAN'
                control.mkdir()
                commands = []
                for name in cleanup:
                    relative_path(root, name)
                    commands.append('rm -f -- '+shlex.quote('/'+name))
                if entry['kind'] == 'board':
                    commands.append('systemd-sysusers')
                build.write(control/'postinst', '#!/bin/sh\nset -eu\nif [ "$1" = configure ]; then\n'
                            +'\n'.join(commands)+'\nfi\n', 0o755)
            result.append(package_tree(root, output, entry['package'], entry['depends'], entry['kind'],
                                       conflicts=entry.get('conflicts',()), replaces=entry.get('replaces',())))
    manifest = {'schema':1, 'profile':profile, 'board':build.BOARD,
                'distribution':identity(build.DISTRIBUTION), 'packages':result,
                'private_configuration_included':False, 'kernel_included':False}
    build.write(output/f'board-{profile}.json', json.dumps(manifest, indent=2)+'\n')
    return manifest


def pack_de(profile, output=None):
    profile = profile_name(profile)
    if profile == 'server':
        raise ValueError('Server has no desktop environment')
    output = output or build.artifact_directory()/'layers'
    work = build.distribution_build()/'layers/work'
    work.mkdir(parents=True, exist_ok=True)
    result = []
    with tempfile.TemporaryDirectory(dir=work) as tmp:
        for entry in desktop_plan(profile):
            root = Path(tmp)/entry['kind']
            root.mkdir()
            if entry['kind'] == 'de-'+profile:
                if profile == 'kde':
                    build.configure_display(profile, root)
                control = root/'DEBIAN'
                control.mkdir()
                gdm = ''
                if profile == 'gnome':
                    # GDM has one distro-owned conffile, not a conf.d interface.
                    # Edit its daemon settings without claiming that file in two packages.
                    gdm = '''python3 - <<'GDM'
import configparser
from pathlib import Path
p = Path('/etc/gdm3/daemon.conf')
c = configparser.ConfigParser(interpolation=None, strict=False)
c.optionxform = str
c.read(p)
if not c.has_section('daemon'): c.add_section('daemon')
c.set('daemon', 'WaylandEnable', 'true')
c.set('daemon', 'XorgEnable', 'false')
c.set('daemon', 'PreferredDisplayServer', 'wayland')
with p.open('w') as stream: c.write(stream)
GDM
'''
                build.write(control/'postinst', '#!/bin/sh\nset -eu\n'
                            'if [ "$1" = configure ]; then\n'+gdm+
                            'systemctl set-default graphical.target\nfi\n', 0o755)
            result.append(package_tree(root, output, entry['package'], entry['depends'], entry['kind']))
    return result


def requested_packages(profile, board=None, distribution=None, include_board=True):
    """Full standard distro dependency closure, without any board payload."""
    distribution = distribution or build.DISTRIBUTION
    specification = resolve_profile(profile_name(profile), distribution)
    requested = [*specification['packages'], *specification['required_packages']]
    entries = plan(profile, board=board, distribution=distribution) if include_board else desktop_plan(profile, distribution)
    for entry in entries:
        requested += [name for name in entry['depends'] if not name.startswith('reimuks-')]
    return list(dict.fromkeys(requested))


def fetch(profile, offline=False, cache=None):
    profile = profile_name(profile)
    if offline:
        source = (cache or build.distribution_build()/('apt-de-'+profile)).resolve()
        receipt_path = source/'fetch-complete.json'
        previous = json.loads(receipt_path.read_text())
        # Re-selection may change package groups, but cannot cross a distro or
        # introduce bytes absent from the previously authenticated receipt.
        expected = identity(build.DISTRIBUTION)
        if any(previous['distribution'][key] != expected[key]
               for key in ('id', 'backend', 'suite', 'architecture')):
            raise ValueError('Offline desktop cache belongs to another distribution')
        specification = resolve_profile(profile, build.DISTRIBUTION)
        selected = selected_archives(source, requested_packages(profile, include_board=False), specification['install_recommends'])
        hashes = {p.name:build.digest(p) for p in selected}
        if any(previous['archives'].get(name) != value for name,value in hashes.items()):
            raise ValueError('Offline desktop selection contains an unverified archive')
        state = build.apt_state('apt-de-'+profile, build.DISTRIBUTION['architecture'], profile=profile)
        if state.resolve() != source.resolve():
            # Reuse authenticated indexes and package bytes without a download.
            config = (source/'apt.conf').read_text().replace(str(source),str(state))
            build.write(state/'apt.conf',config)
            if (state/'lists').is_symlink():
                (state/'lists').unlink()
            else:
                remove_tree(state/'lists')
            (state/'lists').symlink_to((source/'lists').resolve(),target_is_directory=True)
            for path in selected:
                destination = state/'archives'/path.name
                if not destination.exists():
                    try:
                        os.link(path,destination)
                    except OSError:
                        shutil.copyfile(path,destination)
                if build.digest(destination) != hashes[path.name]:
                    raise ValueError('Existing desktop cache file differs from its authenticated source')
        build.write(state/'fetch-complete.json',json.dumps({'distribution':expected,
                    'archives':hashes, 'parent_receipt_sha256':hashlib.sha256(json.dumps(previous,sort_keys=True).encode()).hexdigest()},indent=2)+'\n')
        return state
    if cache is not None:
        raise ValueError('--cache applies to offline fetch or bundle')
    state = build.apt_state('apt-de-'+profile, build.DISTRIBUTION['architecture'], profile=profile)
    build.apt(state, 'update')
    specification = resolve_profile(profile, build.DISTRIBUTION)
    build.apt(state, '--download-only', '--install-recommends' if specification['install_recommends'] else '--no-install-recommends',
              '-y', 'install', *requested_packages(profile, include_board=False))
    selected = selected_archives(state, requested_packages(profile, include_board=False), specification['install_recommends'])
    build.write(state/'fetch-complete.json', json.dumps({'distribution':identity(build.DISTRIBUTION),
                'archives':{p.name:build.digest(p) for p in selected}}, indent=2)+'\n')
    return state


INSTALL = '''#!/bin/sh
set -eu
test "$(id -u)" = 0 || { echo 'Root is required' >&2; exit 1; }
cd "$(dirname "$0")"
sha256sum -c SHA256SUMS
. /etc/os-release
test "$ID/$VERSION_CODENAME" = DISTRIBUTION
test "$(dpkg --print-architecture)" = ARCHITECTURE
apt-get -o Dir::Cache::archives="$PWD/packages/" --no-download RECOMMENDS -y install "$PWD"/packages/*.deb
'''


def bundle_de(profile, cache, output=None):
    profile = profile_name(profile)
    specification = resolve_profile(profile, build.DISTRIBUTION)
    selected = selected_archives(cache, requested_packages(profile, include_board=False), specification['install_recommends'])
    receipt = json.loads((cache/'fetch-complete.json').read_text())
    if receipt['distribution'] != identity(build.DISTRIBUTION):
        raise ValueError('Desktop cache has a different distribution configuration')
    if any(receipt['archives'].get(p.name) != build.digest(p) for p in selected):
        raise ValueError('Desktop cache is not authenticated by its fetch receipt')
    packages = pack_de(profile)
    files = [(p,p.name) for p in selected] + [
        (build.artifact_directory()/'layers'/p['file'],
         p['package']+'_'+p['version']+'_'+build.DISTRIBUTION['architecture']+'.deb') for p in packages]
    manifest = {'schema':1, 'profile':profile, 'distribution':identity(build.DISTRIBUTION),
                'board_drivers_included':False, 'packages':packages,
                'archives':{name:build.digest(p) for p,name in files}}
    output = output or build.artifact_directory()/f'de-{profile}-arm64.tar.gz'
    def emit(result):
        def data(name, value, mode=0o644):
            info = tarfile.TarInfo(name); info.mode=mode; info.size=len(value)
            result.addfile(info, io.BytesIO(value))
        installer = INSTALL.replace('DISTRIBUTION', shlex.quote(build.DISTRIBUTION['id'])).replace(
            'ARCHITECTURE', shlex.quote(build.DISTRIBUTION['architecture'])).replace(
            'RECOMMENDS', '--install-recommends' if specification['install_recommends'] else '--no-install-recommends')
        data('install.sh', installer.encode(), 0o755)
        data('manifest.json', (json.dumps(manifest, indent=2)+'\n').encode())
        data('SHA256SUMS', ''.join(build.digest(p)+'  packages/'+name+'\n' for p,name in files).encode())
        for path,name in files:
            info = tarfile.TarInfo('packages/'+name);info.size=path.stat().st_size;info.mode=0o644
            with path.open('rb') as stream:
                result.addfile(info, stream)
    archive(output, emit)
    return manifest


def install_packages(root, work, saved, profile, context=None):
    """Use target dpkg/fakeroot so file lists and ownership enter the image."""
    output = build.artifact_directory()/'layers'
    manifest = pack_board(profile, context or root, output)
    desktop = pack_de(profile, output) if profile_name(profile) != 'server' else []
    manifest['desktop_packages'] = desktop
    files = [entry['file'] for entry in desktop+manifest['packages']]
    before = work/'layer-fakeroot.state'
    shutil.copyfile(saved, before)
    script = work/'install-layers.sh'
    build.write(script, '#!/bin/sh\nset -eu\numask 022\n'
                'trap \'rm -f /usr/sbin/policy-rc.d\' EXIT\n'
                'printf "#!/bin/sh\\nexit 101\\n" > /usr/sbin/policy-rc.d\nchmod 755 /usr/sbin/policy-rc.d\n'
                +'dpkg --install '+ ' '.join(shlex.quote('/layers/'+name) for name in files)+'\n'
                'dpkg --audit > /work/layer-dpkg-audit.txt\ntest ! -s /work/layer-dpkg-audit.txt\n'
                "dpkg-query -W -f='${Package}\\t${Version}\\t${Architecture}\\t${Status}\\n' > /work/packages.tsv\n", 0o755)
    build.proot(root, ['/usr/bin/fakeroot-tcp', '-i', '/work/layer-fakeroot.state',
                      '-s', '/work/package-fakeroot.state', '/bin/sh', '/work/install-layers.sh'],
                [f'{work}:/work', f'{output}:/layers'])
    return manifest


def install_desktop(root, work, saved, profile, cache):
    """Compose a standard desktop onto a configured base, entirely offline."""
    specification = resolve_profile(profile, build.DISTRIBUTION)
    selected = selected_archives(cache, requested_packages(profile, include_board=False), specification['install_recommends'])
    receipt = json.loads((cache/'fetch-complete.json').read_text())
    if receipt['distribution'] != identity(build.DISTRIBUTION) or any(
            receipt['archives'].get(p.name) != build.digest(p) for p in selected):
        raise ValueError('Desktop dependency closure is not authenticated for this distribution')
    check_os_release((root/'usr/lib/os-release').read_text(), build.DISTRIBUTION)
    shutil.copyfile(saved, work/'layer-fakeroot.state')
    command = ('apt-get -o Dir::Cache::archives=/de-packages/ --no-download '+('--install-recommends' if specification['install_recommends'] else '--no-install-recommends')
               +' -y install '+' '.join(shlex.quote('/de-packages/'+p.name) for p in selected))
    build.write(work/'install-desktop.sh', '#!/bin/sh\nset -eu\numask 022\n'
                'trap \'rm -f /usr/sbin/policy-rc.d\' EXIT\n'
                'printf "#!/bin/sh\\nexit 101\\n" > /usr/sbin/policy-rc.d\nchmod 755 /usr/sbin/policy-rc.d\n'
                +command+'\n', 0o755)
    build.proot(root, ['/usr/bin/fakeroot-tcp', '-i', '/work/layer-fakeroot.state',
                      '-s', '/work/package-fakeroot.state', '/bin/sh', '/work/install-desktop.sh'],
                [f'{work}:/work', f'{cache}/archives:/de-packages'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['plan','fetch','pack','bundle'])
    parser.add_argument('--profile', choices=['server','kde','gnome'], default='kde')
    parser.add_argument('--board', default='w202ds')
    parser.add_argument('--distribution', default=build.DEFAULT)
    parser.add_argument('--context', type=Path, help='Configured distro rootfs supplying desktop templates')
    parser.add_argument('--cache', type=Path, help='Authenticated APT cache for the offline DE bundle')
    parser.add_argument('--offline', action='store_true', help='fetch only; reselect authenticated cached packages without downloading')
    args = parser.parse_args()
    build.select_board(args.board)
    build.select_distribution(args.distribution)
    if args.offline and args.action != 'fetch':
        parser.error('--offline applies only to fetch')
    if args.action == 'plan':
        result = plan(args.profile)
    elif args.action == 'fetch':
        result = {'cache':str(fetch(args.profile,args.offline,args.cache))}
    elif args.action == 'pack':
        result = pack_board(args.profile, args.context or build.profile_directory(args.profile)/'rootfs')
        if args.profile != 'server':
            result['desktop_packages'] = pack_de(args.profile)
    else:
        result = bundle_de(args.profile, args.cache or build.distribution_build()/('apt-de-'+args.profile))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    os.umask(0o022)
    main()
