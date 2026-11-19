"""Publish deterministic rootfs overlays; layer scripts supply the contents."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import tempfile

from board_userspace import install_template, service_link
from user_overlay import pack


@contextmanager
def staging(output):
    output = output.expanduser().absolute()
    if output.exists() or output.is_symlink():
        raise ValueError(f'Choose a new package directory: {output}')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f'.{output.name}-', dir=output.parent) as temporary:
        root = Path(temporary)/'root'
        package = Path(temporary)/'package'
        for directory in (root, package):
            directory.mkdir(mode=0o755)
        yield root, package
        package.rename(output)


def stage_policy(root, layer, selector):
    policy = json.loads((layer/'layer.json').read_text())['policies'][selector]
    for directory in policy.get('files', []):
        install_template(root, layer/directory)
    for relative, unit in policy.get('services', {}).items():
        service_link(root, relative, unit)


def portable(root, export, name, archive, architecture, requires, *, metadata=(), **scope):
    payload = export/archive
    pack(root, payload)
    payload.chmod(0o644)
    files = {}
    for path in (payload, *metadata):
        with path.open('rb') as stream:
            digest = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024*1024), b''):
                digest.update(chunk)
        files[path.name] = digest.hexdigest()
    (export/'package.json').write_text(json.dumps(dict(
        schema=1, id=name, architecture=architecture, requires=requires,
        files=files, **scope), indent=2)+'\n')
