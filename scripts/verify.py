#!/usr/bin/env python3
"""Verify deliverable formats, identities and archive ownership without root."""
import ctypes
import ctypes.util
import hashlib
import json
from pathlib import Path
import stat
import struct
import tarfile
import argparse
import os
from board_userspace import verification_policy, verify_archive
from build import BUILD, digest
import build as backend
from distributions import DEFAULT, identity, resolve_profile, check_os_release, check_package_versions


def unpack_legacy(path):
    data=path.read_bytes()
    if data[:4] != bytes.fromhex('02214c18'):
        raise ValueError('Not legacy LZ4 (LinuxBoot requires 0x184c2102)')
    lib=ctypes.CDLL(ctypes.util.find_library('lz4'))
    lib.LZ4_decompress_safe.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_int,ctypes.c_int]
    offset=4
    output=bytearray()
    while offset<len(data):
        size=struct.unpack_from('<I',data,offset)[0];offset+=4
        if size>len(data)-offset:
            raise ValueError('Truncated legacy LZ4 block')
        dest=ctypes.create_string_buffer(8*1024*1024)
        n=lib.LZ4_decompress_safe(data[offset:offset+size],dest,size,len(dest))
        if n<0:
            raise ValueError('Invalid LZ4 block')
        output.extend(dest.raw[:n]);offset+=size
    return bytes(output)


def cpio_entries(data):
    offset=0
    entries={}
    while True:
        if data[offset:offset+6]!=b'070701':
            raise ValueError('Invalid newc header')
        fields=[int(data[offset+6+i*8:offset+14+i*8],16) for i in range(13)]
        offset+=110
        name=data[offset:offset+fields[11]-1].decode()
        offset=(offset+fields[11]+3)&~3
        body=data[offset:offset+fields[6]]
        if len(body)!=fields[6]:
            raise ValueError('Truncated newc body')
        offset=(offset+fields[6]+3)&~3
        if name=='TRAILER!!!':break
        if name in entries:raise ValueError(f'Duplicate newc path: {name}')
        entries[name]=(fields,body)
    return entries


def verify_initramfs(path):
    e=cpio_entries(unpack_legacy(path))
    if 'etc/distribution.json' in e:
        assert json.loads(e['etc/distribution.json'][1]) == identity(backend.DISTRIBUTION), 'Initramfs distribution differs'
    else:
        assert backend.DISTRIBUTION['id'] == DEFAULT, 'Legacy initramfs has no distribution identity'
    for name in ('init','bin/busybox','bin/grep','bin/ln','bin/ip',
                 'usr/lib/reimuks/initramfs.d/20-hardware',
                 'sbin/blkid','lib/ld-linux-aarch64.so.1','etc/kernel-image.sha256'):
        assert name in e, name
    policy = json.loads((backend.board_directory()/'board.json').read_text()).get('kernel_policy', {})
    for name in policy.get('initramfs_forbidden_paths', []):
        assert name not in e, name
    assert stat.S_ISCHR(e['dev/console'][0][1])
    for name in ('bin/busybox','sbin/blkid'):
        b=e[name][1]
        assert b[:4]==b'\x7fELF' and struct.unpack_from('<H',b,18)[0]==183,name
    meta=json.loads((backend.kernel_directory()/'manifest.json').read_text())
    assert e['etc/kernel-image.sha256'][1].decode().strip()==meta['image_sha256']
    assert sum(name.endswith('.ko') for name in e)==len(meta['module_hashes'])
    return {'entries':len(e),'bytes':path.stat().st_size,'sha256':digest(path)}


def verify_base_metadata(members, shadow):
    for name in ('.', 'etc', 'usr', 'usr/bin', 'usr/lib', 'usr/libexec'):
        if name in members:
            info = members[name]
            assert info.uid == 0 and info.gid == 0, ('Base directory ownership', name)
            assert not info.mode & 0o022, ('Writable base directory', name)
    for name in members:
        assert not name.startswith('etc/ssh/ssh_host_'), ('Machine SSH key in base image', name)
        assert name not in ('etc/shadow-', 'etc/gshadow-'), ('Account backup in base image', name)
        assert name != 'state' and not name.startswith('state/'), ('Host staging residue', name)
        assert name != 'usr/libexec/__pycache__/w202-hall-inputcpython-312.pyc', ('Obsolete board bytecode', name)
    passwords = {line.split(':')[0]: line.split(':')[1] for line in shadow.splitlines() if ':' in line}
    for user in ('root', 'reimuks'):
        assert passwords.get(user, '').startswith(('!', '*')), ('Unlocked base account', user)


def verify_rootfs(path,profile):
    policies = verification_policy(backend.board_directory(), profile)
    with tarfile.open(path,'r|gz') as t:
        wanted={'etc/shadow','etc/passwd','usr/bin/bash','var/lib/dpkg/status','usr/lib/os-release',
                'usr/lib/reimuks/distribution.json',
                'etc/machine-id'}
        for policy in policies:
            wanted.update(policy.get('files', []))
            wanted.update(policy.get('contains', {}))
        members={}
        contents={}
        kernel_modules=[]
        for m in t:
            name=m.name.removeprefix('./')
            members[name]=m
            if name in wanted:
                contents[name]=t.extractfile(m).read()
            if name.endswith('.ko') and m.isfile():
                # Vim's Korean tutor is also named *.ko. A kernel module is
                # a relocatable ELF object, not merely a filename suffix.
                header=t.extractfile(m).read(20)
                if is_module_object(header):
                    kernel_modules.append(name)
            assert not name.startswith(('usr/lib/modules/', 'lib/modules/', 'boot/Image-')), name
        def read(name):return contents[name]
        verify_archive(policies, members, contents)
        check_os_release(read('usr/lib/os-release').decode(), backend.DISTRIBUTION)
        if 'usr/lib/reimuks/distribution.json' in contents:
            assert json.loads(read('usr/lib/reimuks/distribution.json')) == identity(backend.DISTRIBUTION), 'Rootfs distribution differs'
        else:
            assert backend.DISTRIBUTION['id'] == DEFAULT, 'Legacy rootfs has no distribution identity'
        for name in members:
            assert not name.startswith('/') and '..' not in Path(name).parts,name
            assert name.split('/',1)[0] not in ('host-rootfs','packages','work','output'),name
        verify_base_metadata(members, read('etc/shadow').decode())
        assert members['etc/shadow'].uid==0
        assert members['etc/shadow'].mode & 0o007 == 0
        assert members['etc/passwd'].uid==0
        passwd=read('etc/passwd').decode()
        users={x.split(':')[0]:int(x.split(':')[2]) for x in passwd.splitlines()}
        assert members['home/reimuks'].uid==users['reimuks']
        assert users.get('messagebus',0)>0
        assert members['var/lib/dbus'].uid in (0,users['messagebus'])
        assert read('usr/bin/bash')[:4]==b'\x7fELF'
        data=read('usr/bin/bash');assert struct.unpack_from('<H',data,18)[0]==183
        status=read('var/lib/dpkg/status').decode()
        blocks=[b for b in status.split('\n\n') if b.strip()]
        for b in blocks:
            assert 'Status: install ok installed' in b,b[:120]
            assert '\nArchitecture: arm64' in b or '\nArchitecture: all' in b,b[:120]
        specification = resolve_profile(profile, backend.DISTRIBUTION)
        installed_versions = {}
        for block in blocks:
            fields = dict(line.split(': ', 1) for line in block.splitlines()
                          if line and not line[0].isspace() and ': ' in line)
            installed_versions[fields['Package']] = fields['Version']
        optional = set(backend.DISTRIBUTION.get('additional_packages', {}).get('packages', []))
        assert not optional.intersection(installed_versions), ('Optional applications in base rootfs', sorted(optional.intersection(installed_versions)))
        check_package_versions(specification, installed_versions)
        required=specification['required_packages']
        for pkg in required:
            assert any(b.startswith('Package: '+pkg+'\n') for b in blocks),pkg
        target=specification['target']
        assert members['etc/systemd/system/default.target'].linkname.endswith('/'+target)
        if specification.get('display_manager'):
            assert members['etc/systemd/system/display-manager.service'].linkname.endswith('/'+specification['display_manager']+'.service')
        assert not read('etc/machine-id').strip()
        assert not kernel_modules, ('Kernel modules belong in a separate deployment bundle', kernel_modules)
        return {'entries':len(members),'packages':len(blocks),'bytes':path.stat().st_size,'sha256':digest(path)}


def is_module_object(header):
    return (len(header) >= 18 and header[:4] == b'\x7fELF' and
            header[5] in (1, 2) and
            int.from_bytes(header[16:18], 'little' if header[5] == 1 else 'big') == 1)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--board', default=os.environ.get('REIMUKS_BOARD', 'w202ds'))
    parser.add_argument('--distribution',default=os.environ.get('REIMUKS_DISTRIBUTION', DEFAULT))
    parser.add_argument('--profile', choices=['server', 'kde', 'gnome'],
                        help='Verify only this rootfs, independently of initramfs or other profiles')
    args=parser.parse_args()
    backend.select_board(args.board)
    initramfs = None
    if args.profile is None:
        backend.select_distribution(DEFAULT)
        initramfs=verify_initramfs(backend.artifact_directory()/'initramfs-arm64.cpio.lz4')
    backend.select_distribution(args.distribution)
    output=backend.artifact_directory()
    result={'distribution':identity(backend.DISTRIBUTION)}
    if initramfs is not None:
        result['initramfs'] = initramfs
    profiles = [args.profile] if args.profile else ['server', 'kde']
    for profile in profiles:
        result[profile]=verify_rootfs(output/f'desktop-{profile}-arm64-rootfs.tar.gz',profile)
    (output/'verification.json').write_text(json.dumps(result,indent=2)+'\n')
    entries=[(f'desktop-{profile}-arm64-rootfs.tar.gz',result[profile]) for profile in profiles]
    if initramfs is not None and backend.DISTRIBUTION['id'] == DEFAULT:
        entries.insert(0, ('initramfs-arm64.cpio.lz4',result['initramfs']))
    (output/'SHA256SUMS').write_text(''.join(f'{v["sha256"]}  {name}\n' for name,v in entries))
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
