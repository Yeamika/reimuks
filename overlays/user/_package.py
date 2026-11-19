"""Write a private artifact and its receipt without publishing an incomplete layer."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tarfile
import tempfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'scripts'))
from user_overlay import pack, validate


def archive_or_source(produce_source, existing, output, name, requires, check, board=None):
    output = output.expanduser()
    if output.exists() or output.is_symlink():
        raise ValueError(f'Use a new output directory: {output}')
    previous_umask = os.umask(0o077)
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.user-layer-', dir=output.parent) as work:
            stage = Path(work)/'package'
            stage.mkdir()
            artifact = stage/f'{name}-overlay.tar.gz'
            if existing is None:
                pack(produce_source(Path(work)), artifact)
            else:
                shutil.copyfile(existing.expanduser(), artifact)
            with tarfile.open(artifact, 'r:gz') as bundle:
                check(validate(bundle.getmembers()), bundle.extractfile)
            digest = hashlib.sha256()
            with artifact.open('rb') as payload:
                for chunk in iter(lambda: payload.read(1024*1024), b''):
                    digest.update(chunk)
            receipt = dict(schema=1, id=name, architecture='all', private=True,
                           requires=requires, files={artifact.name: digest.hexdigest()})
            if board:
                receipt['board'] = board
            (stage/'package.json').write_text(json.dumps(receipt, indent=2)+'\n')
            stage.rename(output)
    finally:
        os.umask(previous_umask)
