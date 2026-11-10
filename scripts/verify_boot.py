#!/usr/bin/env python3
"""Verify collected boot output hashes and ARM64 EFI/FV file formats."""
import argparse
import hashlib
import json
from pathlib import Path
import struct


def verify(directory, manifest_name):
    directory=directory.resolve()
    record=json.loads((directory/manifest_name).read_text())
    results={}
    for name,expected in record['artifacts'].items():
        path=(directory/name).resolve()
        if directory not in path.parents:
            raise ValueError('artifact escapes output directory')
        data=path.read_bytes()
        if len(data)!=expected['bytes'] or hashlib.sha256(data).hexdigest()!=expected['sha256']:
            raise ValueError('artifact identity mismatch: '+name)
        if path.suffix.lower()=='.efi':
            if len(data)<64 or data[:2]!=b'MZ': raise ValueError('missing DOS/PE header: '+name)
            pe=struct.unpack_from('<I',data,60)[0]
            if pe+94>len(data) or data[pe:pe+4]!=b'PE\0\0': raise ValueError('bad PE header: '+name)
            if struct.unpack_from('<H',data,pe+4)[0]!=0xaa64: raise ValueError('not AArch64: '+name)
            if struct.unpack_from('<H',data,pe+24)[0]!=0x20b: raise ValueError('not PE32+: '+name)
            if struct.unpack_from('<H',data,pe+92)[0]!=10: raise ValueError('not an EFI application: '+name)
        if path.suffix.lower()=='.fd':
            if len(data)!=0x200000 or data[40:44]!=b'_FVH': raise ValueError('invalid W202DS FV: '+name)
            size=struct.unpack_from('<H',data,48)[0]
            if size<56 or size%2 or size>len(data) or sum(struct.unpack_from('<'+'H'*(size//2),data))&0xffff:
                raise ValueError('invalid FV header checksum: '+name)
        results[name]={'bytes':len(data),'sha256':expected['sha256']}
    if not results: raise ValueError('no boot artifacts')
    return results


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('directory',type=Path)
    p.add_argument('--manifest',required=True)
    a=p.parse_args()
    print(json.dumps(verify(a.directory,a.manifest),indent=2))


if __name__=='__main__': main()
