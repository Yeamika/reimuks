#!/usr/bin/env python3
"""Verify identities of opaque artifacts collected from a board boot project."""
import argparse
import hashlib
import json
from pathlib import Path


def verify(directory, manifest_name):
    directory = directory.resolve()
    record = json.loads((directory / manifest_name).read_text())
    results = {}
    for name, expected in record['artifacts'].items():
        path = (directory / name).resolve()
        if directory not in path.parents:
            raise ValueError('artifact escapes output directory')
        data = path.read_bytes()
        identity = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        if identity != {'bytes': expected['bytes'], 'sha256': expected['sha256']}:
            raise ValueError('artifact identity mismatch: ' + name)
        results[name] = identity
    if not results:
        raise ValueError('no boot artifacts')
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--manifest', required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.directory, args.manifest), indent=2))


if __name__ == '__main__':
    main()
