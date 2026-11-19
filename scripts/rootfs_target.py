"""Install selected Debian layer packages into a standalone root filesystem."""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shlex
import shutil
import subprocess
import tarfile
import tempfile

import build
from compose_target import existing_file, identifier, relative_name, resolve_layers, write_target
from distributions import check_os_release, identity, resolve_profile
from startup_preflight import verify as verify_startup
from tree_cleanup import remove_tree
from user_overlay import archive, merge, validate


def payload(files):
    matches = [path for name, path in files.items() if name.endswith('.tar.gz')]
    if len(matches) != 1:
        raise ValueError('Expected one archive in a rootfs layer')
    return matches[0]


def layout(target, packages, device_root):
    if not target.get('board') or not target.get('distribution'):
        raise ValueError('A rootfs preset needs a board and distribution')
    spec = target.get('rootfs')
    if not isinstance(spec, dict) or spec.keys() - {
            'profile', 'base', 'kernel', 'install', 'adapter', 'device_state'}:
        raise ValueError('Preset does not define a supported rootfs layout')
    if 'profile' in spec:
        identifier(spec['profile'], 'rootfs profile')
    installers = spec.get('install', [])
    if not isinstance(installers, list):
        raise ValueError('rootfs install must be a list of installer layers')
    primary = [spec.get('base'), spec.get('kernel'), spec.get('adapter'), *installers]
    for name in primary:
        if identifier(name, 'rootfs layer') not in packages:
            raise ValueError(f'Missing rootfs layer: {name}')
    if len(set(primary)) != len(primary):
        raise ValueError('Duplicate rootfs layer')
    adapter = packages[spec['adapter']][1]
    covered = set(adapter.get('requires', ()))
    for name, (_, data, _) in packages.items():
        if (name not in primary and name not in covered and not data.get('private')
                and not name.startswith('apps-')):
            raise ValueError(f'No rootfs installation method for {name}')
    device_path = None
    if 'device_state' in spec:
        device_path = existing_file(device_root, spec['device_state'])
    return spec, device_path


def unpack_installer(source, output):
    """Installer archives contain plain files and their local Debian repository."""
    output.mkdir()
    with tarfile.open(source, 'r|gz') as contents:
        for entry in contents:
            name = entry.name.removeprefix('./').rstrip('/')
            if name in ('', '.'):
                continue
            dest = output/relative_name(name)
            if entry.isdir():
                dest.mkdir(parents=True, exist_ok=True)
            elif entry.isfile():
                dest.parent.mkdir(parents=True, exist_ok=True)
                with contents.extractfile(entry) as content, dest.open('xb') as output_file:
                    shutil.copyfileobj(content, output_file)
                dest.chmod(entry.mode & 0o755)
            else:
                raise ValueError(f'Invalid installer member: {entry.name}')
    if not (output/'install.sh').is_file():
        raise ValueError(f'{source}: missing install.sh')


def verify_adapter_covers(covered, debs):
    """Portable board layers must have matching payloads in the adapter."""
    expected = {}

    def files(contents):
        for entry in contents:
            name = entry.name.removeprefix('./')
            if entry.isfile():
                yield name, ('file', hashlib.sha256(contents.extractfile(entry).read()).digest())
            elif entry.issym():
                yield name, ('link', entry.linkname)
            elif not entry.isdir():
                raise ValueError(f'Unexpected file type in board layer: {name}')

    for source in covered:
        with tarfile.open(source, 'r|gz') as contents:
            expected.update(files(contents))
    if not expected:
        return
    for deb in debs:
        with subprocess.Popen(['dpkg-deb', '--fsys-tarfile', deb], stdout=subprocess.PIPE) as process:
            with tarfile.open(fileobj=process.stdout, mode='r|') as contents:
                for name, record in files(contents):
                    if expected.get(name) == record:
                        del expected[name]
            process.stdout.read()
            if process.wait():
                raise ValueError(f'Could not inspect {deb.name}')
        if not expected:
            return
    raise ValueError(f'Board adapter differs from selected layers: {next(iter(expected))}')


def combine_private(output, private, device_path, staged_root):
    """Copy only kernel-declared device files and the selected user layers."""
    with ExitStack() as stack:
        additions = {}

        def add(source, allowed=None):
            handle = stack.enter_context(tarfile.open(source, 'r:gz'))
            entries = validate(handle.getmembers())
            if allowed is not None:
                parents = {str(p) for name in allowed for p in PurePosixPath(name).parents}
                for name in allowed:
                    if name not in entries or not entries[name].isfile():
                        raise ValueError(f'Missing kernel device file: {name}')
                entries = {name: item for name, item in entries.items() if name in allowed
                           or (name in parents and item.isdir())}
            for name, item in entries.items():
                if name in additions:
                    if item.isdir() and additions[name][1].isdir():
                        continue
                    raise ValueError(f'Overlapping private files: {name}')
                additions[name] = handle, item

        if device_path:
            contract = json.loads((staged_root/'usr/lib/reimuks/deployment-requirements.json').read_text())
            if contract.get('schema') != 2 or not contract['device'].get('files'):
                raise ValueError('Kernel has no device-state file declaration')
            add(device_path, set(contract['device']['files']))
        for source in private:
            add(source)
        validate(item for _, item in additions.values())

        def emit(result):
            for _, (source, entry) in sorted(additions.items()):
                result.addfile(entry, source.extractfile(entry) if entry.isfile() else None)

        archive(output, emit)


def read_status(path):
    installed = {}
    for stanza in path.read_text().split('\n\n'):
        fields = dict(line.split(': ', 1) for line in stanza.splitlines()
                      if line and not line[0].isspace() and ': ' in line)
        if fields:
            if fields.get('Status') != 'install ok installed':
                raise ValueError('Desktop cache has unconfigured packages')
            installed[fields['Package']] = fields['Version']
    return installed


def reuse_desktop(root, work, profile, manifest, adapter):
    """Reuse a configured desktop only when the selected closure still matches."""
    from fakeroot_state import relocate
    from urllib.parse import unquote

    archives = manifest.get('archives')
    if manifest.get('profile') != profile or not isinstance(archives, dict):
        return None
    prepared = build.profile_directory(profile)
    cache_work = prepared/'work'
    source = prepared/'rootfs'
    apt = build.package_cache('apt-'+profile)/'fetch-complete.json'
    status_path = Path('var/lib/dpkg/status')
    adapter_hashes = {name: build.digest(path) for name, path in adapter.items()
                      if name.endswith('.deb') and '/' not in name}
    required = read_status(root/status_path)
    with build.profile_lock(profile):
        try:
            if not ((cache_work/'configured').is_file()
                    and (cache_work/'clean-rootfs-v1').is_file()
                    and (cache_work/'dpkg-audit.txt').stat().st_size == 0):
                return None
            build.check_rootfs(profile)
            receipt = json.loads(apt.read_text())
            if receipt['distribution'] != identity(build.DISTRIBUTION):
                return None
            for name, digest in archives.items():
                if adapter_hashes.get(name) == digest:
                    continue
                if receipt['archives'].get(name) != digest:
                    return None
                package, version, _ = name.removesuffix('.deb').rsplit('_', 2)
                required[package] = unquote(version)
            ready = read_status(source/status_path)
            if any(ready.get(name) != version for name, version in required.items()):
                return None
            passwords = {fields[0]: fields[1] for line in (source/'etc/shadow').read_text().splitlines()
                         if len(fields := line.split(':')) > 1}
            if any(not passwords.get(name) or set(passwords[name]) - {'!', '*'}
                   for name in ('root', 'reimuks')):
                return None
            ownership = cache_work/'fakeroot.state'
            if not ownership.is_file():
                return None
        except (OSError, ValueError, KeyError):
            return None

        candidate = work/'cached-desktop'
        print(f'Reusing the configured {profile} cache after matching package versions and archive hashes',
              flush=True)
        try:
            subprocess.run(['cp', '--archive', '--reflink=auto', '--', source, candidate], check=True)
            relocate(ownership, work/'base.state', source, candidate)
            for name in ('usr/lib/reimuks/distribution.json',
                         'usr/lib/systemd/system/reimuks-ssh-hostkeys.service',
                         'etc/systemd/system/ssh.service.d/10-hostkeys.conf'):
                original, destination = root/name, candidate/name
                if original.is_file():
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(original, destination)
            remove_tree(root)
            candidate.rename(root)
        finally:
            remove_tree(candidate)
    return sorted(ready.keys()-required.keys())


def package_state(work):
    values = {}
    for line in (work/'packages.tsv').read_text().splitlines():
        name, version, architecture, status = line.split('\t')
        if status != 'install ok installed' or architecture not in (build.DISTRIBUTION['architecture'], 'all'):
            raise ValueError(f'Package {name} is not configured for this rootfs')
        values[name] = version
    return values


def materialize(target, packages, spec, device_path, output):
    os.umask(0o022)
    for _, data, files in packages.values():
        for name, path in files.items():
            if build.digest(path) != data['files'][name]:
                raise ValueError(f'{data["id"]}: SHA-256 mismatch for {name}')
    build.select_board(target['board'])
    build.select_distribution(target['distribution'])
    if (build.DISTRIBUTION['architecture'] != target['architecture']
            or build.DISTRIBUTION['backend'] != 'apt-dpkg'):
        raise ValueError('Rootfs preset requires a matching Debian APT distribution')
    profile = resolve_profile(spec.get('profile', 'server'), build.DISTRIBUTION)
    if not shutil.which('fakeroot-tcp'):
        raise ValueError('Rootfs assembly requires host fakeroot-tcp')
    if not ((build.SHARED_BUILD/'tools/proot').is_file()
            and (build.TOOLS/'usr/bin/qemu-aarch64').is_file()):
        build.prepare_tools()

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.reimuks-rootfs-', dir=output.parent) as directory:
        scratch = Path(directory)
        root, work = scratch/'root', scratch/'work'
        root.mkdir()
        work.mkdir()
        try:
            result = install(root, work, target, packages, spec, profile)
            raw = scratch/'rootfs.tar'
            print('Archiving the configured root filesystem', flush=True)
            subprocess.run([
                'fakeroot-tcp', '-i', work/'installed.state', '--', 'tar', '--numeric-owner',
                '--sort=name', '--one-file-system', '--xattrs', '--acls',
                '--exclude=./dev/*', '--exclude=./proc/*', '--exclude=./sys/*',
                '--exclude=./run/*', '--exclude=./tmp/*', '--exclude=./work',
                '--exclude=./host-rootfs', '-cf', raw, '-C', root, '.',
            ], check=True)
            private = [payload(files) for _, data, files in packages.values() if data.get('private')]
            candidate = scratch/'rootfs.tar.gz'
            if private or device_path:
                print('Applying private user and kernel settings', flush=True)
                selected = scratch/'private.tar.gz'
                combine_private(selected, private, device_path, root)
                merge(raw, selected, candidate)
            else:
                with candidate.open('wb') as destination:
                    subprocess.run(['gzip', '-n', '-6', '-c', raw], check=True, stdout=destination)
                candidate.chmod(0o644)
            checksum = build.digest(candidate)
            os.link(candidate, output)
            return dict(result, sha256=checksum, bytes=output.stat().st_size)
        finally:
            remove_tree(root)


def install(root, work, target, packages, spec, profile):
    def inputs(name):
        return packages[name][2]

    base = payload(inputs(spec['base']))
    kernel = payload(inputs(spec['kernel']))
    adapter = inputs(spec['adapter'])
    debs = [path for name, path in adapter.items() if name.endswith('.deb')]
    if not debs:
        raise ValueError('Debian board adapter contains no packages')
    roles = {spec['base'], spec['kernel'], spec['adapter'], *spec.get('install', [])}
    covered = [payload(inputs(name)) for name in packages[spec['adapter']][1]['requires'] if name not in roles]
    verify_adapter_covers(covered, debs)

    print('Extracting the distribution base and preparing offline packages', flush=True)
    with (work/'base-tar.log').open('w+') as log:
        extraction = subprocess.run([
            'fakeroot-tcp', '-s', work/'base.state', '--', 'tar', '--numeric-owner',
            '--same-owner', '--same-permissions', '--xattrs', '--acls', '-xpf', base, '-C', root,
        ], stderr=log)
        if extraction.returncode:
            log.seek(0)
            raise ValueError(f'Cannot extract distribution base: {log.read()[-2000:]}')
    expected = identity(build.DISTRIBUTION)
    marker = json.loads((root/'usr/lib/reimuks/distribution.json').read_text())
    # The digest covers the entire distribution configuration, including
    # unrelated desktop/app choices. Match the runtime family and let offline
    # APT and dpkg verify exact dependencies across independent build revisions.
    def same_distribution(marker):
        return isinstance(marker, dict) and all(
            marker.get(key) == expected[key] for key in ('id', 'backend', 'suite', 'architecture'))
    if not same_distribution(marker):
        raise ValueError('Distribution base does not match this preset')
    check_os_release((root/'usr/lib/os-release').read_text(), build.DISTRIBUTION)
    provenance = {spec['base']: marker}

    script = []
    requested_packages = set()
    installers = list(spec.get('install', []))
    apps = [name for name, (_, data, _) in packages.items() if name.startswith('apps-')
            and not data.get('private')]
    extras = None
    for name in [*installers, *apps]:
        bundle = work/name
        unpack_installer(payload(inputs(name)), bundle)
        manifest = json.loads((bundle/'manifest.json').read_text())
        if not same_distribution(manifest.get('distribution')):
            raise ValueError(f'{name}: bundle was built for a different distribution')
        provenance[name] = manifest['distribution']
        requested = manifest.get('requested', [])
        if not isinstance(requested, list) or any(not isinstance(pkg, str) for pkg in requested):
            raise ValueError(f'{name}: invalid package selection')
        if not requested and (name in apps or 'profile' not in spec):
            raise ValueError(f'{name}: missing package selection')
        requested_packages.update(requested)
        if name in installers and len(installers) == 1 and 'profile' in spec:
            extras = reuse_desktop(root, work, spec['profile'], manifest, adapter)

    def stage(name, source):
        destination = work/relative_name(name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(source, destination)
        except OSError:
            shutil.copyfile(source, destination)

    stage('kernel.tar.gz', kernel)
    for name, source in adapter.items():
        if name.endswith('.deb'):
            stage('board/'+name, source)
    expected_debs = {}
    for source in debs:
        package, version = subprocess.check_output(
            ['dpkg-deb', '-f', source, 'Package', 'Version'], text=True).splitlines()
        expected_debs[package.split(': ', 1)[1]] = version.split(': ', 1)[1]

    if extras is None:
        script.extend(f'printf "%s\\n" {shlex.quote("Installing "+name)}\n'
                      f'/bin/sh /work/{name}/install.sh' for name in installers)
    elif extras:
        script.append('dpkg --purge '+shlex.join(extras))
    script.append('''printf '%s\n' 'Installing kernel and board integration'
tar --numeric-owner --same-owner --same-permissions -xpf /work/kernel.tar.gz -C /
mkdir -p /work/apt/lists/partial /work/apt/archives/partial /work/apt/empty
apt-get -o Dir::Etc::sourcelist=/dev/null -o Dir::Etc::sourceparts=/work/apt/empty \
    -o Dir::State::lists=/work/apt/lists -o Dir::Cache::archives=/work/apt/archives \
    --no-install-recommends --no-remove -y install ''' +
        shlex.join('/work/board/'+name for name in adapter if name.endswith('.deb')))
    script.extend(f'printf "%s\\n" {shlex.quote("Installing "+name)}\n'
                  f'/bin/sh /work/{name}/install.sh' for name in apps)
    script.append('''printf '%s\n' 'Checking package configuration and kernel'
systemd-sysusers
release=$(cat /usr/lib/reimuks/kernel-release)
sha256sum --quiet -c /usr/lib/reimuks/kernel-files.sha256
image_hash=$(cat /usr/lib/reimuks/kernel-image.sha256)
case "$image_hash" in
    *[!0-9a-f]*|'') sha256sum --quiet -c /usr/lib/reimuks/kernel-image.sha256 ;;
    *)
        test "${#image_hash}" = 64
        printf '%s  %s\n' "$image_hash" "boot/Image-$release" | sha256sum --quiet -c -
        ;;
esac
depmod -a "$release"
test -s "/usr/lib/modules/$release/modules.dep"
cp -an /etc/skel/. /home/reimuks/
chown -R reimuks:reimuks /home/reimuks
usermod --password '!' root
usermod --password '!' reimuks
rm -f /etc/shadow- /etc/gshadow- /var/lib/dbus/machine-id /etc/ssh/ssh_host_*
: > /etc/machine-id
dpkg --audit > /work/dpkg-audit.txt
test ! -s /work/dpkg-audit.txt
dpkg-query -W -f='${Package}\\t${Version}\\t${Architecture}\\t${Status}\\n' > /work/packages.tsv
''')
    build.write(work/'install.sh', '''#!/bin/sh
set -eu
umask 022
stage_apt=/etc/apt/apt.conf.d/99reimuks-stage
test ! -e /usr/sbin/policy-rc.d
test ! -e "$stage_apt"
trap 'rm -f /usr/sbin/policy-rc.d "$stage_apt"' EXIT
install -m 0644 /work/apt.conf "$stage_apt"
printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d
chmod 755 /usr/sbin/policy-rc.d
'''+'\n'.join(script), 0o755)
    build.write(work/'apt.conf', '''APT::Get::Remove "false";
DPkg::Options { "--force-confdef"; "--force-confold"; };
''')
    build.proot(root, ['/usr/bin/fakeroot-tcp', '-i', '/work/base.state',
                      '-s', '/work/installed.state', '/bin/sh', '/work/install.sh'],
                [f'{work}:/work'], stdin=subprocess.DEVNULL)

    installed = package_state(work)
    mandatory = requested_packages.union(profile['required_packages'])
    if missing := mandatory - installed.keys():
        raise ValueError(f'Missing configured packages: {", ".join(sorted(missing))}')
    if different := {name for name, version in expected_debs.items() if installed.get(name) != version}:
        raise ValueError(f'Incorrect board package versions: {", ".join(sorted(different))}')
    profile_name = spec.get('profile', 'server')
    build.configure_locale(profile_name, root)
    if 'profile' in spec:
        build.configure_desktop_graphics(root)
    report = verify_startup(root, profile_name, build.proot)
    build.write(root/'usr/lib/reimuks/startup-preflight.json', json.dumps(report, indent=2)+'\n')
    build.write(root/'usr/lib/reimuks/preset.json', json.dumps(dict(
        id=target['id'], layers=list(packages), distribution_inputs=provenance), indent=2)+'\n')
    return {'packages': len(installed), 'startup_checks': len(report['commands'])}


def assemble(config, root, output, *, device_root, board=None, plan=False, app_overlays=(),
             user_overlays=(), user_input_root=None, clean=False):
    output = output.expanduser().absolute()
    if not output.name.endswith('.tar.gz'):
        raise ValueError('Rootfs output must end with .tar.gz')
    options = dict(board=board, app_overlays=app_overlays, user_overlays=user_overlays,
                   user_input_root=user_input_root)
    old_output = output.exists() or output.is_symlink()
    if clean:
        targets = device_root.resolve()/'artifacts/targets'
        if output.parent != targets or targets.resolve() != targets:
            raise ValueError('--clean is limited to the board build output directory')
        if old_output and (output.is_symlink() or not output.is_file()):
            raise ValueError(f'Expected a regular rootfs archive: {output}')
        if old_output and not plan:
            # Check that all selected inputs resolve before deleting a previous result.
            with resolve_layers(config, root, plan=True, **options) as layers:
                layout(layers[0], layers[1], device_root.resolve())
            output.unlink()
    elif old_output and not plan:
        raise ValueError(f'Output already exists: {output}; use a new --output or --clean with a preset')
    with resolve_layers(config, root, plan=plan, **options) as layers:
        target, packages, planned = layers
        spec, device_path = layout(target, packages, device_root.resolve())
        result = write_target(target, packages, None, plan=True, planned=planned)
        result.update(format='rootfs', output=str(output),
                      private=bool(result['private'] or device_path))
        if plan and clean:
            result['remove_previous_output'] = old_output
        if not plan:
            result.update(materialize(target, packages, spec, device_path, output))
        return result
