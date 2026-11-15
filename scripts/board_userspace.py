"""Stage board mechanisms, then apply REIMUKS profile policy offline."""
import json
import configparser
from pathlib import Path
import shutil
import struct
import subprocess
import sys
from board_exports import component, exported_file, relative_path, manifest as board_manifest


REPO = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = REPO / 'build'


def controls_binary(staging, name, architecture, flat=False):
    binary = staging / name if flat else staging / 'usr/libexec' / name
    if not binary.is_file():
        raise ValueError(f'Missing board integration executable: {name}; build the selected board controls first')
    machine = {'arm64': 183, 'aarch64': 183, 'x86_64': 62}.get(architecture)
    header = binary.read_bytes()[:20]
    if (machine is None or len(header) != 20 or header[:6] != b'\x7fELF\x02\x01' or
            struct.unpack_from('<H', header, 18)[0] != machine):
        raise ValueError(f'Board integration executable must be ELF64 for {architecture}')
    return binary


def install_template(root, source, private=False):
    if not source.is_dir():
        raise ValueError(f'Missing filesystem template: {source}')
    existing_directories = {p: p.stat().st_mode & 0o7777
                            for p in [root, *root.rglob('*')]
                            if p.is_dir() and not p.is_symlink()}
    # copytree(dirs_exist_ok=True) merges directories but does not replace an
    # existing symlink. Shared-library install trees must remain repeatable.
    for entry in source.rglob('*'):
        if entry.is_symlink():
            target = root/entry.relative_to(source)
            if target.is_dir() and not target.is_symlink():
                raise ValueError('Template symlink conflicts with a directory: '+str(target))
            target.unlink(missing_ok=True)
    def copy_file(src, dst):
        target = Path(dst)
        connections = root / 'etc/NetworkManager/system-connections'
        if target.parent == connections:
            # NM may save the same UUID under a user-chosen filename. Defaults
            # initialize a missing connection, never reset a saved connection.
            if target.exists():
                return str(target)
            config = configparser.ConfigParser(interpolation=None, strict=False)
            config.read(src)
            identifier = config.get('connection', 'uuid', fallback=None)
            if identifier:
                for existing in connections.glob('*'):
                    if not existing.is_file():
                        continue
                    current = configparser.ConfigParser(interpolation=None, strict=False)
                    try:
                        current.read(existing)
                    except configparser.Error:
                        continue
                    if current.get('connection', 'uuid', fallback=None) == identifier:
                        return str(existing)
        result = shutil.copy2(src, dst)
        if not private:
            target.chmod(target.stat().st_mode & 0o7777 & ~0o022)
        return result
    shutil.copytree(source, root, dirs_exist_ok=True, symlinks=True, copy_function=copy_file)
    for path in [root, *root.rglob('*')]:
        if path.is_dir() and not path.is_symlink():
            mode = existing_directories.get(path)
            if mode is not None:
                path.chmod(mode)
            elif not private:
                path.chmod(path.stat().st_mode & 0o7777 & ~0o022)


def install_component(root, board, name):
    userspace = component(board, name)
    manifest = userspace / 'artifacts.json'
    artifact_root = None
    if manifest.exists():
        data = json.loads(manifest.read_text())
        if data.get('schema') != 1:
            raise ValueError('Unsupported userspace artifact schema')
        relative = Path(data['rootfs'])
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Invalid userspace artifact root')
        base = board_manifest(board)[0] if data.get('base') == 'project' else userspace
        artifact_root = relative_path(base, relative)
        for filename in data['required']:
            path = Path(filename)
            if path.is_absolute() or '..' in path.parts:
                raise ValueError('Invalid userspace artifact file')
            if not (artifact_root / path).is_file():
                raise ValueError(f'Missing {name} userspace artifact: {filename}; build and stage board userspace first')
    if artifact_root is not None:
        install_template(root, artifact_root)
    # Staging may contain older copies of scripts and units alongside binaries.
    # Always apply current source templates last so cached build output cannot
    # silently restore an obsolete startup policy.
    if (userspace / 'rootfs').is_dir() or artifact_root is None:
        install_template(root, userspace / 'rootfs')


def service_link(root, relative, unit=None):
    # Policy paths are relative to systemd's target directory in the image.
    path = Path(relative)
    if path.is_absolute() or len(path.parts) != 2 or '..' in path.parts:
        raise ValueError(f'Invalid service link: {relative}')
    link = root / 'etc/systemd/system' / path
    if link.exists() or link.is_symlink():
        link.unlink()
    if unit is not None:
        if Path(unit).name != unit or not unit.endswith('.service'):
            raise ValueError(f'Invalid service unit: {unit}')
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to('/usr/lib/systemd/system/' + unit)


def install_rootfs(root, profile, board=None):
    board = Path(board) if board is not None else REPO / 'devices/w202ds'
    policy = json.loads((board / 'rootfs/policy.json').read_text())
    if policy.get('schema') != 1:
        raise ValueError('Unsupported board rootfs policy schema')
    # server/kde are the legacy internal names for desktop/server and desktop/kde.
    name = profile if profile.startswith('desktop/') else 'desktop/' + profile
    if name not in policy['profiles']:
        raise ValueError(f'Unsupported board rootfs profile: {name}')
    selected = policy['profiles'][name]
    layers = [policy['common']]
    controls = []
    artifacts = []
    architecture = json.loads((board / 'board.json').read_text()).get('architecture')
    if selected.get('desktop_common'):
        layers.append(policy['desktop_common'])
    layers.append(selected)
    enabled = {}
    for layer in layers:
        for artifact in layer.get('rootfs_artifacts', []):
            staging = relative_path(ARTIFACT_ROOT, artifact['rootfs'])
            for binary in artifact['required_elf']:
                # Validate the declared ELF without imposing a libexec layout.
                path = Path(binary)
                controls_binary(staging / path.parent, path.name, architecture, flat=True)
            artifacts.append(staging)
        for artifact in layer.get('control_artifacts', []):
            staging = relative_path(ARTIFACT_ROOT, artifact['rootfs'])
            controls.extend(controls_binary(staging, binary, architecture)
                            for binary in artifact['executables'])
    for layer in layers:
        for component in layer.get('components', []):
            install_component(root, board, component)
        enabled.update(layer.get('services', {}))
    for staging in artifacts:
        install_template(root, staging)
    # All component defaults precede every REIMUKS overlay.
    for layer in layers:
        for overlay in layer.get('overlays', []):
            install_template(root, board / 'rootfs' / overlay)
        for relative in layer.get('remove', []):
            path = Path(relative)
            if path.is_absolute() or '..' in path.parts or not path.parts:
                raise ValueError(f'Invalid obsolete file path: {relative}')
            (root / path).unlink(missing_ok=True)
        for relative in layer.get('disable', []):
            enabled.pop(relative, None)
            service_link(root, relative)
    for relative, unit in enabled.items():
        service_link(root, relative, unit)
    for binary in controls:
        destination = root / 'usr/libexec' / binary.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(binary, destination)
        destination.chmod(0o755)


def prepare_rootfs(root, board, profile):
    policy = json.loads((board / 'rootfs/policy.json').read_text())
    name = profile if profile.startswith('desktop/') else 'desktop/' + profile
    selected = policy['profiles'][name]
    layers = [policy['common']]
    if selected.get('desktop_common'):
        layers.append(policy['desktop_common'])
    layers.append(selected)
    for layer in layers:
        for command in layer.get('preparers', []):
            script = relative_path(board, command)
            subprocess.run([sys.executable, str(script), '--rootfs', str(root.resolve())], check=True)


def verification_policy(board, profile):
    policy = json.loads((board / 'rootfs/policy.json').read_text())
    name = profile if profile.startswith('desktop/') else 'desktop/' + profile
    selected = policy['profiles'][name]
    layers = [policy['common']]
    if selected.get('desktop_common'):
        layers.append(policy['desktop_common'])
    layers.append(selected)
    return [layer.get('verify', {}) for layer in layers]


def verify_archive(policies, members, contents):
    for policy in policies:
        for name in policy.get('files', []):
            assert name in contents, name
        for name in policy.get('executables', []):
            assert members[name].mode & 0o111, name
        for name in policy.get('symlinks', []):
            assert members[name].issym(), name
        for name in policy.get('absent', []):
            assert name not in members, name
        for prefix in policy.get('absent_prefixes', []):
            assert not any(name == prefix or name.startswith(prefix + '/')
                           for name in members), prefix
        for name, target in policy.get('link_targets', {}).items():
            assert members[name].issym() and members[name].linkname == target, name
        for name, expected in policy.get('contains', {}).items():
            for value in expected:
                assert value in contents[name].decode(), (name, value)


def install_initramfs(root, board=None):
    board = Path(board) if board is not None else REPO / 'devices/w202ds'
    config = json.loads((board/'board.json').read_text())
    for destination, name in config.get('initramfs_exports', {}).items():
        source = exported_file(board, name)
        target = relative_path(root, destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    for destination, source in config.get('initramfs_policy_files', {}).items():
        target = relative_path(root, destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(relative_path(board, source), target)
    install_template(root, board / 'initramfs/rootfs')
