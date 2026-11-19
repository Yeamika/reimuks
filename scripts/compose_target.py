"""Assemble a target archive with optional application and private layers."""
from contextlib import ExitStack, contextmanager
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tarfile
import tempfile


IDENTIFIER = re.compile(r'[a-z0-9][a-z0-9._-]*\Z')
SHA256 = re.compile(r'[0-9a-f]{64}\Z')
IDENTITY = ('schema', 'id', 'architecture', 'board', 'distribution')
REPO = Path(__file__).resolve().parents[1]


def identifier(value, field):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError(f'Invalid {field}: {value!r}')
    return value


def relative_name(value):
    if (not isinstance(value, str) or not value or '\\' in value or
            any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise ValueError(f'Invalid relative path: {value!r}')
    name = PurePosixPath(value)
    if name.is_absolute() or not name.parts or '..' in name.parts or str(name) != value:
        raise ValueError(f'Invalid relative path: {value!r}')
    return name


def existing_file(root, name):
    path = (root/relative_name(name)).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f'Path escapes {root}: {name}')
    if not path.is_file():
        raise ValueError(f'Missing file: {root/name}')
    return path


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Duplicate JSON field: {key}')
        result[key] = value
    return result


def document(path, fields):
    value = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique_object)
    if not isinstance(value, dict) or type(value.get('schema')) is not int or value['schema'] != 1:
        raise ValueError(f'{path}: expected an object with schema 1')
    if unknown := value.keys() - (fields | set(IDENTITY)):
        raise ValueError(f'{path}: unknown fields: {", ".join(sorted(unknown))}')
    identifier(value.get('id'), 'id')
    identifier(value.get('architecture'), 'architecture')
    if 'board' in value:
        identifier(value['board'], 'board')
    if 'distribution' in value:
        relative_name(value['distribution'])
    return value


def package(receipt, target, earlier, *, explicit_private=False):
    data = document(receipt, {'files', 'requires', 'private'})
    name = data['id']
    if name in earlier:
        raise ValueError(f'Duplicate layer: {name}')
    for key in ('architecture', 'board', 'distribution'):
        compatibility = data.get(key)
        if key == 'architecture' and compatibility == 'all':
            continue
        if compatibility is not None and compatibility != target.get(key):
            raise ValueError(f'{name}: {key} {compatibility!r} does not match target {target.get(key)!r}')
    requires = data.get('requires', [])
    if not isinstance(requires, list):
        raise ValueError(f'{name}: requires must be a list')
    for dependency in requires:
        if identifier(dependency, 'required layer') not in earlier:
            raise ValueError(f'{name}: required layer {dependency} must appear earlier in the recipe')
    private = data.get('private', False)
    if type(private) is not bool:
        raise ValueError(f'{name}: private must be true or false')
    if explicit_private and not private:
        raise ValueError(f'{name}: --user-overlay requires a private package receipt')
    if private and not (explicit_private or target.get('allow_private')):
        raise ValueError(f'{name}: private layer requires allow_private in the target recipe')
    records = data.get('files')
    if not isinstance(records, dict) or not records:
        raise ValueError(f'{name}: files must map relative paths to SHA-256 hashes')
    files = {}
    reserved = {*records, 'package.json'}
    for filename, digest in sorted(records.items()):
        file = relative_name(filename)
        if file == PurePosixPath('package.json') or any(str(parent) in reserved for parent in file.parents):
            raise ValueError(f'{name}: conflicting package path: {file}')
        if not isinstance(digest, str) or not SHA256.fullmatch(digest):
            raise ValueError(f'{name}: invalid SHA-256 for {file}')
        files[filename] = existing_file(receipt.parent, filename)
    return data, files


def layer_reference(entry, earlier):
    """A recipe may name the owning producer for an absent cached receipt."""
    if isinstance(entry, str):
        return entry, None
    if not isinstance(entry, dict) or set(entry) != {'receipt', 'id', 'producer', 'requires'}:
        raise ValueError('A source layer needs receipt, id, producer and requires')
    name = identifier(entry['id'], 'layer id')
    if name in earlier:
        raise ValueError(f'Duplicate layer: {name}')
    reference = relative_name(entry['receipt'])
    if reference.name != 'package.json':
        raise ValueError('A source layer receipt must be named package.json')
    if not isinstance(entry['requires'], list):
        raise ValueError(f'{name}: requires must be a list')
    for dependency in entry['requires']:
        if identifier(dependency, 'required layer') not in earlier:
            raise ValueError(f'{name}: required layer {dependency} must appear earlier in the recipe')
    script = relative_name(entry['producer'])
    if script.parts[0] not in ('devices', 'overlays', 'distributions') or script.suffix != '.py':
        raise ValueError(f'{name}: producer must be a Python script in a source layer')
    producer = existing_file(REPO, script.as_posix())
    if not producer.is_relative_to(REPO/script.parts[0]):
        raise ValueError(f'{name}: producer escapes its source tree')
    return str(reference), producer


def produce_package(producer, target, output, root):
    command = [sys.executable, '-B', str(producer), '--architecture',
               target['architecture'], '--output', str(output)]
    env = dict(os.environ, REIMUKS_PACKAGE_ROOT=str(root))
    if 'distribution' in target:
        env['REIMUKS_DISTRIBUTION'] = target['distribution']
    result = subprocess.run(command, cwd=REPO, env=env, capture_output=True, text=True)
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise ValueError(f'Could not build {output.name}' + (f': {detail}' if detail else ''))


def add_recipe_layer(root, target, packages, planned, entry, *, plan):
    reference, producer = layer_reference(entry, packages)
    candidate = root/relative_name(reference)
    if producer and not (candidate.exists() or candidate.is_symlink()):
        destination = candidate.parent.resolve()
        if not destination.is_relative_to(root) or destination == root:
            raise ValueError(f'Package destination escapes {root}: {reference}')
        if plan:
            name = entry['id']
            packages[name] = (reference, {'requires': entry['requires']}, {})
            planned[name] = {'id': name, 'action': 'build', 'receipt': reference,
                             'producer': entry['producer']}
            return
        produce_package(producer, target, destination, root)
    receipt = existing_file(root, reference)
    data, files = package(receipt, target, packages)
    if producer and (data['id'] != entry['id'] or
                     data.get('requires', []) != entry['requires'] or data.get('private')):
        raise ValueError(f'{reference}: package does not match the recipe; refresh its cache')
    packages[data['id']] = (reference, data, files)


def recipe(config, seen=()):
    config = config.resolve()
    if config in seen:
        raise ValueError(f'Cyclic preset inheritance: {config.name}')
    target = document(config, {'layers', 'allow_private', 'extends', 'app_overlays',
                               'user_overlays', 'rootfs'})
    own_layers = target.get('layers', [])
    if not isinstance(own_layers, list):
        raise ValueError('layers must be a list of package receipts in assembly order')
    inherited = {}
    if 'extends' in target:
        path = relative_name(target.pop('extends'))
        if len(path.parts) != 1 or path.suffix != '.json':
            raise ValueError('extends must name a sibling preset JSON')
        inherited = recipe(existing_file(config.parent, path.as_posix()), (*seen, config))
        for field in ('board', 'distribution', 'architecture'):
            if inherited.get(field) != target.get(field):
                raise ValueError(f'{config.name}: inherited {field} does not match')
        own_layers = inherited['layers'] + own_layers
        for field in ('allow_private', 'rootfs'):
            if field in inherited:
                target.setdefault(field, inherited[field])
    target['layers'] = own_layers
    if not target['layers']:
        raise ValueError('layers must be a nonempty list of package receipts in assembly order')
    if type(target.get('allow_private', False)) is not bool:
        raise ValueError('allow_private must be true or false')
    for field in ('app_overlays', 'user_overlays'):
        values = target.get(field, [])
        if not isinstance(values, list):
            raise ValueError(f'{field} must be a list of layer names')
        for name in values:
            identifier(name, field)
        if field in inherited or field in target:
            target[field] = inherited.get(field, []) + values
    return target


def read_target(config, root, board=None, *, plan=False):
    target = recipe(config.expanduser())
    if board and target.get('board', board) != board:
        raise ValueError(f'Target board {target["board"]!r} does not match --board {board!r}')
    packages, planned = {}, {}
    for entry in target['layers']:
        add_recipe_layer(root, target, packages, planned, entry, plan=plan)
    return target, packages, planned


def add_app_overlays(root, target, packages, planned, groups, *, plan):
    if not groups:
        return
    if 'distribution' not in target:
        raise ValueError('--app-overlay requires a distribution in the target recipe')
    prefix = PurePosixPath('apps')/target['distribution']/target['architecture']
    producers = REPO/'overlays/apps'
    for group in groups:
        name = identifier(group, 'app overlay group')
        layer = 'apps-'+name
        reference = str(prefix/name/'package.json')
        candidate = root/reference
        producer = producers/name/'build.py'
        if not (candidate.exists() or candidate.is_symlink()) and producer.is_file():
            if not producer.resolve().is_relative_to(producers.resolve()):
                raise ValueError(f'{name}: app producer escapes its source tree')
            add_recipe_layer(root, target, packages, planned,
                             dict(id=layer, receipt=reference,
                                  producer=producer.relative_to(REPO).as_posix(),
                                  requires=['distribution']), plan=plan)
            if layer in planned:
                continue
            data = packages[layer][1]
        else:
            data, files = package(existing_file(root, reference), target, packages)
            packages[data['id']] = (reference, data, files)
        if (data['id'] != layer or data.get('private', False) or
                data.get('distribution') != target['distribution']):
            raise ValueError(f'{reference}: expected a public app overlay for {target["distribution"]}')


def _parse_user_overlay(value):
    if '=' in value:
        name, source = value.split('=', 1)
        if not source:
            raise ValueError(f'Missing input path for user overlay {name!r}')
        return identifier(name, 'user overlay'), Path(source).expanduser().resolve()
    if value.endswith('.json') or '/' in value or '\\' in value:
        return None, value
    return identifier(value, 'user overlay'), None


def add_user_overlays(root, target, packages, references, stack, *, input_root=None, plan=False):
    """Resolve cached packages or run a layer's own package.py --input --output."""
    private_sources = input_root.expanduser().resolve() if input_root else root.parent/'private-overlay-inputs'
    board = target.get('board')
    producers = (REPO/'overlays/user').resolve()
    scratch = None
    planned = {}
    for reference in references:
        name, source = _parse_user_overlay(reference)
        if name is None:
            receipt = existing_file(root, reference)
        else:
            if name in packages:
                raise ValueError(f'Duplicate layer: {name}')
            producer = (producers/name/'package.py').resolve()
            if not producer.is_relative_to(producers) or not producer.is_file():
                raise ValueError(f'Unknown user overlay: {name}')
            if source is None:
                candidates = ([private_sources/board/name] if board else []) + [private_sources/name]
                source = next((p for p in candidates if p.exists() or p.is_symlink()), None)
            if source is None and not input_root:
                candidates = ([f'private/{board}/{name}/package.json'] if board else [])
                candidates.append(f'private/{name}/package.json')
                reference = next((p for p in candidates if (root/p).exists() or (root/p).is_symlink()), None)
                if reference:
                    receipt = existing_file(root, reference)
            if source is not None:
                if not (source.is_file() or source.is_dir()):
                    raise ValueError(f'Missing input for user overlay {name}: {source}')
                if plan:
                    packages[name] = (None, {'private': True}, {})
                    planned[name] = {'id': name, 'action': 'build', 'source': str(source)}
                    continue
                if scratch is None:
                    scratch = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix='reimuks-user-')))
                command = [sys.executable, '-B', str(producer), '--input', str(source),
                           '--output', str(scratch/name)]
                env = dict(os.environ, REIMUKS_BOARD=board or '')
                result = subprocess.run(command, check=False, capture_output=True, text=True, env=env)
                if result.returncode:
                    detail = result.stderr.strip()
                    raise ValueError(f'User overlay {name} could not be packaged'
                                     + (f': {detail}' if detail else ''))
                receipt = existing_file(scratch, f'{name}/package.json')
                reference = None
            elif not reference or input_root:
                raise ValueError(f'No input for user overlay {name}; provide --user-overlay {name}=PATH')
        data, files = package(receipt, target, packages, explicit_private=True)
        if name is not None and data['id'] != name:
            raise ValueError(f'Expected user overlay {name}, got {data["id"]}')
        packages[data['id']] = (reference, data, files)
    return planned


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2)+'\n').encode('utf-8')


class HashReader:
    def __init__(self, stream):
        self.stream = stream
        self.digest = hashlib.sha256()

    def read(self, size):
        data = self.stream.read(size)
        self.digest.update(data)
        return data


@contextmanager
def resolve_layers(config, root, *, board=None, plan=False, app_overlays=(),
                   user_overlays=(), user_input_root=None):
    root = root.expanduser().resolve()
    target, packages, planned = read_target(config, root, board, plan=plan)
    add_app_overlays(root, target, packages, planned,
                     (*target.get('app_overlays', []), *app_overlays), plan=plan)
    with ExitStack() as stack:
        planned.update(add_user_overlays(root, target, packages,
                                         (*target.get('user_overlays', []), *user_overlays),
                                         stack, input_root=user_input_root, plan=plan))
        yield target, packages, planned


def assemble(config, root, output, *, board=None, plan=False, app_overlays=(),
             user_overlays=(), user_input_root=None):
    if not plan:
        output = output.expanduser()
        if output.exists() or output.is_symlink():
            raise ValueError(f'Output already exists: {output}')
    with resolve_layers(config, root, board=board, plan=plan, app_overlays=app_overlays,
                        user_overlays=user_overlays, user_input_root=user_input_root) as inputs:
        target, packages, planned = inputs
        return write_target(target, packages, output, plan=plan, planned=planned)


def write_target(target, packages, output, *, plan, planned):
    private = any(data.get('private', False) for _, data, _ in packages.values())
    result = {key: target[key] for key in IDENTITY if key in target}
    result.update(private=private)
    if plan:
        return dict(result, layers=[planned.get(name) or dict(id=name, receipt=reference, files=len(files))
                                    for name, (reference, _, files) in packages.items()])
    output.parent.mkdir(parents=True, exist_ok=True)
    result['layers'] = [{'id': name, 'receipt': f'layers/{name}/package.json'} for name in packages]
    raw = tempfile.NamedTemporaryFile(dir=output.parent, prefix='.target-', delete=False)
    partial = Path(raw.name)
    try:
        with raw, tarfile.open(fileobj=raw, mode='w|', format=tarfile.PAX_FORMAT) as bundle:
            checks = []

            def item(name, size):
                entry = tarfile.TarInfo(name)
                entry.size = size
                entry.mode = 0o600 if private else 0o644
                return entry

            def add_data(name, data, checksum=True):
                bundle.addfile(item(name, len(data)), io.BytesIO(data))
                if checksum:
                    checks.append(f'{hashlib.sha256(data).hexdigest()}  {name}\n')

            add_data('manifest.json', json_bytes(result))
            for name, (_, data, files) in packages.items():
                prefix = f'layers/{name}'
                add_data(f'{prefix}/package.json', json_bytes(data))
                for filename, source in files.items():
                    member = f'{prefix}/{filename}'
                    expected = data['files'][filename]
                    with source.open('rb') as stream:
                        info = os.fstat(stream.fileno())
                        if not stat.S_ISREG(info.st_mode):
                            raise ValueError(f'Expected a regular artifact: {source}')
                        reader = HashReader(stream)
                        bundle.addfile(item(member, info.st_size), reader)
                        if reader.digest.hexdigest() != expected or stream.read(1):
                            raise ValueError(f'{name}: SHA-256 mismatch for {filename}')
                    checks.append(f'{expected}  {member}\n')
            add_data('SHA256SUMS', ''.join(checks).encode('utf-8'), checksum=False)
        partial.chmod(0o600 if private else 0o644)
        # Never overwrite a published target or any of the input packages.
        os.link(partial, output)
    finally:
        partial.unlink(missing_ok=True)
    return dict(result, output=str(output.resolve()))
