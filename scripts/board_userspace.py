"""Stage board mechanisms, then apply REIMUKS profile policy offline."""
import json
import hashlib
import configparser
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
from board_exports import component, exported_file, relative_path, output_path, manifest as board_manifest
from output_paths import board_root


REPO = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = None  # Optional caller override; otherwise resolve the selected board at use time.


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
        if not private and ('__pycache__' in entry.relative_to(source).parts or entry.suffix in ('.pyc','.pyo')):
            continue
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
    shutil.copytree(source, root, dirs_exist_ok=True, symlinks=True, copy_function=copy_file,
                    ignore=None if private else shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo'))
    for path in [root, *root.rglob('*')]:
        if path.is_dir() and not path.is_symlink():
            mode = existing_directories.get(path)
            if mode is not None:
                path.chmod(mode)
            elif not private:
                path.chmod(path.stat().st_mode & 0o7777 & ~0o022)


def validated_component_artifacts(board, name):
    userspace = component(board, name)
    manifest = userspace / 'artifacts.json'
    artifact_root = None
    required_hashes = {}
    if manifest.exists():
        data = json.loads(manifest.read_text())
        if data.get('schema') != 1:
            raise ValueError('Unsupported userspace artifact schema')
        relative = Path(data['rootfs'])
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Invalid userspace artifact root')
        if data.get('base') == 'project':
            base, exports = board_manifest(board)
            artifact_root = output_path(base, relative, exports['build']['output'])
        else:
            artifact_root = relative_path(userspace, relative)
        for filename in data['required']:
            path = Path(filename)
            if path.is_absolute() or '..' in path.parts:
                raise ValueError('Invalid userspace artifact file')
            if not (artifact_root / path).is_file():
                raise ValueError(f'Missing {name} userspace artifact: {filename}; build and stage board userspace first')
        # Firmware is mandatory board payload, even when it is not executable.
        required_hashes = data.get('required_sha256', {})
        for filename, expected in required_hashes.items():
            if (filename not in data['required'] or not isinstance(expected, str) or
                    len(expected) != 64 or any(c not in '0123456789abcdef' for c in expected)):
                raise ValueError('Invalid required artifact hash: '+filename)
            actual = hashlib.sha256((artifact_root/filename).read_bytes()).hexdigest()
            if actual != expected:
                raise ValueError('Board artifact hash mismatch: '+filename)
    return userspace, artifact_root, required_hashes


def install_component(root, board, name):
    userspace, artifact_root, required_hashes = validated_component_artifacts(board, name)
    if artifact_root is not None:
        install_template(root, artifact_root)
    # Staging may contain older copies of scripts and units alongside binaries.
    # Always apply current source templates last so cached build output cannot
    # silently restore an obsolete startup policy.
    if (userspace / 'rootfs').is_dir() or artifact_root is None:
        install_template(root, userspace / 'rootfs')
    if required_hashes:
        checks = root/'usr/lib/reimuks/firmware'/(name+'.sha256')
        checks.parent.mkdir(parents=True, exist_ok=True)
        checks.write_text(''.join(digest+'  '+filename+'\n'
                                  for filename, digest in sorted(required_hashes.items())))
        checks.chmod(0o644)


def service_link(root, relative, unit=None):
    # Policy paths are relative to systemd's target directory in the image.
    path = Path(relative)
    if path.is_absolute() or len(path.parts) != 2 or '..' in path.parts:
        raise ValueError(f'Invalid service link: {relative}')
    link = root / 'etc/systemd/system' / path
    if link.exists() or link.is_symlink():
        link.unlink()
    if unit is not None:
        if Path(unit).name != unit or not unit.endswith(('.service', '.timer')):
            raise ValueError(f'Invalid service unit: {unit}')
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to('/usr/lib/systemd/system/' + unit)


def _merge_layer_policy(target, source, layer_root):
    for key, value in source.items():
        if key == 'files':
            target.setdefault('_file_overlays', []).extend(
                relative_path(layer_root, item) for item in value)
        elif key == 'preparers':
            target.setdefault('_preparer_paths', []).extend(
                relative_path(layer_root, item) for item in value)
        elif key == 'verify':
            verification = target.setdefault('verify', {})
            for name, entries in value.items():
                if isinstance(entries, dict):
                    verification.setdefault(name, {}).update(entries)
                elif isinstance(entries, list):
                    verification.setdefault(name, []).extend(entries)
                else:
                    verification[name] = entries
        elif isinstance(value, list):
            target.setdefault(key, []).extend(value)
        elif isinstance(value, dict):
            target.setdefault(key, {}).update(value)
        else:
            target[key] = value


def _layer_root(board, reference):
    path = Path(reference)
    if path.is_absolute() or '..' in path.parts or not path.parts:
        raise ValueError('Invalid overlay reference: '+reference)
    if path.parts[0] == 'services':
        if len(path.parts) != 2:
            raise ValueError('Invalid shared service overlay: '+reference)
        root = REPO/'overlays'/path
    else:
        if len(path.parts) != 1:
            raise ValueError('Invalid board overlay: '+reference)
        root = board/'overlays'/path
    return root.resolve()


def _configured_policy_layers(board, profile, only=None):
    board_file = board/'board.json'
    if not board_file.is_file():
        return None
    board_id = json.loads(board_file.read_text()).get('board')
    name = profile.removeprefix('desktop/')
    config_path = REPO/'config/boards'/board_id/(name+'.json')
    if not config_path.is_file():
        if not (board/'rootfs/policy.json').is_file():
            raise ValueError(f'Unsupported board rootfs profile: desktop/{name}')
        return None
    config = json.loads(config_path.read_text())
    if config.get('schema') != 1 or config.get('board') != board_id:
        raise ValueError('Board profile configuration identity mismatch')
    expected_profile = 'desktop/'+name
    if config.get('profile') != expected_profile:
        raise ValueError('Board profile configuration profile mismatch')
    selectors = ('board', 'board-de', 'board-profile')
    if only is not None and only not in selectors:
        raise ValueError('Unavailable board layer: '+only)
    result = {key: {} for key in selectors}
    for reference in config.get('overlays', []):
        root = _layer_root(board, reference)
        descriptor_path = root/'layer.json'
        if not descriptor_path.is_file():
            raise ValueError('Missing layer descriptor: '+str(descriptor_path))
        descriptor = json.loads(descriptor_path.read_text())
        if descriptor.get('schema') != 1 or descriptor.get('id') != Path(reference).name:
            raise ValueError('Overlay descriptor identity mismatch: '+reference)
        for selector in selectors:
            policy = descriptor.get('policies', {}).get(selector)
            if policy:
                _merge_layer_policy(result[selector], policy, root)
    layers = [(key, result[key]) for key in selectors]
    return [value for key, value in layers if only is None or key == only]


def policy_layers(board, profile, only=None):
    """Resolve selected overlay manifests into board package responsibilities."""
    configured = _configured_policy_layers(board, profile, only)
    if configured is not None:
        return configured
    policy = json.loads((board / 'rootfs/policy.json').read_text())
    if policy.get('schema') != 1:
        raise ValueError('Unsupported board rootfs policy schema')
    name = profile if profile.startswith('desktop/') else 'desktop/' + profile
    if name not in policy['profiles']:
        raise ValueError(f'Unsupported board rootfs profile: {name}')
    selected = policy['profiles'][name]
    legacy = [('board', dict(policy['common']))]
    if selected.get('desktop_common'):
        legacy.append(('board-de', dict(policy['desktop_common'])))
    legacy.append(('board-profile', dict(selected)))
    for _, value in legacy:
        value['_file_overlays'] = [
            relative_path(board/'rootfs', item) for item in value.pop('overlays', [])]
        value['_preparer_paths'] = [
            relative_path(board, item) for item in value.pop('preparers', [])]
    if only is not None and only not in dict(legacy):
        raise ValueError('Unavailable board layer: '+only)
    return [value for key, value in legacy if only is None or key == only]


def validate_rootfs_inputs(board, profile):
    """Hardware inputs are mandatory before composition, for every desktop."""
    for layer in policy_layers(board, profile):
        for name in layer.get('components', []):
            validated_component_artifacts(board, name)


def install_rootfs(root, profile, board=None, only=None):
    board = Path(board) if board is not None else REPO / 'devices/w202ds'
    layers = policy_layers(board, profile, only)
    artifact_base = ARTIFACT_ROOT or board_root(board.name)
    controls = []
    artifacts = []
    architecture = json.loads((board / 'board.json').read_text()).get('architecture')
    enabled = {}
    for layer in layers:
        for artifact in layer.get('rootfs_artifacts', []):
            staging = relative_path(artifact_base, artifact['rootfs'])
            for binary in artifact['required_elf']:
                # Validate the declared ELF without imposing a libexec layout.
                path = Path(binary)
                controls_binary(staging / path.parent, path.name, architecture, flat=True)
            artifacts.append(staging)
        for artifact in layer.get('control_artifacts', []):
            staging = relative_path(artifact_base, artifact['rootfs'])
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
        for overlay in layer.get('_file_overlays', []):
            install_template(root, overlay)
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


def prepare_rootfs(root, board, profile, only=None):
    layers = policy_layers(board, profile, only)
    for layer in layers:
        for script in layer.get('_preparer_paths', []):
            subprocess.run([sys.executable, str(script), '--rootfs', str(root.resolve())], check=True)


def verification_policy(board, profile):
    layers = policy_layers(board, profile)
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
