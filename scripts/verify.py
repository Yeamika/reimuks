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
from build import BUILD, digest


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
    for name in ('init','w202diag','bin/busybox','sbin/blkid','lib/ld-linux-aarch64.so.1','etc/kernel-image.sha256'):
        assert name in e, name
    assert e['w202diag'][1]==b'init'
    assert stat.S_ISCHR(e['dev/console'][0][1])
    for name in ('bin/busybox','sbin/blkid'):
        b=e[name][1]
        assert b[:4]==b'\x7fELF' and struct.unpack_from('<H',b,18)[0]==183,name
    meta=json.loads((BUILD/'kernel/manifest.json').read_text())
    assert e['etc/kernel-image.sha256'][1].decode().strip()==meta['image_sha256']
    assert sum(name.endswith('.ko') for name in e)==len(meta['module_hashes'])
    return {'entries':len(e),'bytes':path.stat().st_size,'sha256':digest(path)}


def verify_rootfs(path,profile):
    meta=json.loads((BUILD/'kernel/manifest.json').read_text())
    with tarfile.open(path,'r|gz') as t:
        wanted={'etc/passwd','usr/bin/bash','var/lib/dpkg/status',
                'usr/lib/reimuks/kernel-release','usr/lib/reimuks/kernel-image.sha256','etc/machine-id'}
        members={}
        contents={}
        module_hashes={}
        for m in t:
            name=m.name.removeprefix('./')
            members[name]=m
            if name in wanted:
                contents[name]=t.extractfile(m).read()
            module_prefix=f'usr/lib/modules/{meta["release"]}/'
            if name.startswith(module_prefix) and name.endswith('.ko'):
                module_hashes[name.removeprefix(module_prefix)]=hashlib.file_digest(t.extractfile(m),'sha256').hexdigest()
            if name==f'boot/Image-{meta["release"]}':
                assert hashlib.file_digest(t.extractfile(m),'sha256').hexdigest()==meta['image_sha256']
        def read(name):return contents[name]
        for name in members:
            assert not name.startswith('/') and '..' not in Path(name).parts,name
            assert name.split('/',1)[0] not in ('host-rootfs','packages','work','output'),name
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
        required=['systemd-sysv','udev','kmod']+(['plasma-workspace','sddm'] if profile=='kde' else [])
        for pkg in required:
            assert any(b.startswith('Package: '+pkg+'\n') for b in blocks),pkg
        assert module_hashes==meta['module_hashes']
        assert read('usr/lib/reimuks/kernel-release').decode().strip()==meta['release']
        assert read('usr/lib/reimuks/kernel-image.sha256').decode().strip()==meta['image_sha256']
        target='graphical.target' if profile=='kde' else 'multi-user.target'
        assert members['etc/systemd/system/default.target'].linkname.endswith('/'+target)
        if profile=='kde':
            assert members['etc/systemd/system/display-manager.service'].linkname.endswith('/sddm.service')
        assert not read('etc/machine-id').strip()
        assert sum(n.endswith('.ko') for n in members)==len(meta['module_hashes'])
        return {'entries':len(members),'packages':len(blocks),'bytes':path.stat().st_size,'sha256':digest(path)}


def main():
    output=BUILD/'artifacts'
    result={'initramfs':verify_initramfs(output/'initramfs-arm64.cpio.lz4')}
    for profile in ('server','kde'):
        result[profile]=verify_rootfs(output/f'desktop-{profile}-arm64-rootfs.tar.gz',profile)
    (output/'verification.json').write_text(json.dumps(result,indent=2)+'\n')
    (output/'SHA256SUMS').write_text(''.join(f'{v["sha256"]}  {name}\n' for name,v in [
        ('initramfs-arm64.cpio.lz4',result['initramfs']),
        ('desktop-server-arm64-rootfs.tar.gz',result['server']),('desktop-kde-arm64-rootfs.tar.gz',result['kde'])]))
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
