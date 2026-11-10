#!/usr/bin/env python3
"""Import a matched kernel/modules set and produce legacy LZ4 newc initramfs."""
import argparse
import ctypes
import ctypes.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import sys
from build import BUILD, REPO, digest, write, proot


def import_kernel(image, modules, config, identity):
    meta = json.loads(identity.read_text())
    release = meta['release']
    if modules.name != release:
        raise SystemExit('Module directory and identity release differ')
    for key, path in [('image_sha256', image), ('config_sha256', config)]:
        if digest(path) != meta[key]:
            raise SystemExit(f'Input hash mismatch: {key}')
    data = image.read_bytes()
    if data[56:60] != b'ARM\x64':
        raise SystemExit('Expected an uncompressed ARM64 Image')
    if 'CONFIG_RD_LZ4=y' not in config.read_text():
        raise SystemExit('Kernel lacks legacy LZ4 initrd support')
    files = sorted(modules.rglob('*.ko'))
    expected = meta.get('standard_modules', 0) + meta.get('board_modules', 0)
    if len(files) != expected:
        raise SystemExit(f'Module count mismatch: {len(files)} != {expected}')
    hashes = {}
    vermagics = set()
    for f in files:
        m = re.search(rb'vermagic=([^\0]+)', f.read_bytes())
        if not m or m[1].decode().split()[0] != release:
            raise SystemExit(f'Module release mismatch: {f}')
        vermagics.add(m[1].decode().strip())
        hashes[str(f.relative_to(modules))] = digest(f)
    if len(vermagics) != 1:
        raise SystemExit(f'Inconsistent module vermagic: {vermagics}')
    target = BUILD / 'kernel'
    if target.exists():
        raise SystemExit(f'Refusing to replace kernel input: {target}')
    target.mkdir()
    shutil.copyfile(image, target / 'Image')
    shutil.copyfile(config, target / 'config')
    shutil.copytree(modules, target / 'modules' / release, symlinks=True)
    for name in ('build', 'source'):
        p = target / 'modules' / release / name
        if p.is_symlink():
            p.unlink()
    meta.update(module_hashes=hashes, vermagic=sorted(vermagics),
                inputs={k: str(p.resolve()) for k,p in
                        [('image',image),('modules',modules),('config',config),('identity',identity)]})
    write(target / 'manifest.json', json.dumps(meta, indent=2)+'\n')
    return meta


def newc(root):
    out = bytearray()
    def entry(name, mode, content=b'', major=0, minor=0):
        names = name.encode()+b'\0'
        fields = [len(out)//4+1, mode, 0, 0, 1, 0, len(content), 0, 0, major, minor, len(names), 0]
        out.extend(b'070701' + ''.join(f'{x:08x}' for x in fields).encode() + names)
        out.extend(b'\0' * (-len(out)%4))
        out.extend(content)
        out.extend(b'\0' * (-len(out)%4))
    for p in sorted(root.rglob('*')):
        s = p.lstat()
        name = str(p.relative_to(root))
        data = os.readlink(p).encode() if p.is_symlink() else p.read_bytes() if p.is_file() else b''
        entry(name, s.st_mode, data)
    entry('dev/console', stat.S_IFCHR | 0o600, major=5, minor=1)
    entry('dev/null', stat.S_IFCHR | 0o666, major=1, minor=3)
    entry('TRAILER!!!', 0)
    out.extend(b'\0' * (-len(out)%512))
    return bytes(out)


def legacy_lz4(data):
    lib = ctypes.CDLL(ctypes.util.find_library('lz4'))
    lib.LZ4_compressBound.argtypes = [ctypes.c_int]
    lib.LZ4_compress_default.argtypes = [ctypes.c_void_p,ctypes.c_void_p,ctypes.c_int,ctypes.c_int]
    out = bytearray(struct.pack('<I',0x184c2102))
    for start in range(0,len(data),8*1024*1024):
        block = data[start:start+8*1024*1024]
        size = lib.LZ4_compressBound(len(block))
        dest = ctypes.create_string_buffer(size)
        n = lib.LZ4_compress_default(block,dest,len(block),size)
        if n <= 0:
            raise RuntimeError('LZ4 compression failed')
        out.extend(struct.pack('<I',n))
        out.extend(dest.raw[:n])
    return bytes(out)


def initramfs():
    meta = json.loads((BUILD/'kernel/manifest.json').read_text())
    release = meta['release']
    root = BUILD/'initramfs/root'
    if root.exists():
        raise SystemExit(f'Refusing to overwrite {root}')
    for d in ('bin','sbin','lib','etc','dev','proc','sys','run','newroot'):
        (root/d).mkdir(parents=True,exist_ok=True)
    server = BUILD/'server/rootfs'
    shutil.copyfile(server/'usr/bin/busybox',root/'bin/busybox')
    (root/'bin/busybox').chmod(0o755)
    for app in ('sh','mount','cat','tr','wc','tail','od','modprobe','mdev','sleep','uname','mkdir','switch_root','setsid','cttyhack','reboot'):
        (root/'bin'/app).symlink_to('busybox')
    shutil.copyfile(server/'usr/sbin/blkid',root/'sbin/blkid')
    (root/'sbin/blkid').chmod(0o755)
    for name in ('libblkid.so.1','libc.so.6','ld-linux-aarch64.so.1'):
        shutil.copyfile(server/'usr/lib/aarch64-linux-gnu'/name,root/'lib'/name)
        (root/'lib'/name).chmod(0o755)
    shutil.copyfile(REPO/'initramfs/init',root/'init')
    (root/'init').chmod(0o755)
    (root/'w202diag').symlink_to('init')
    write(root/'etc/early-modules','')
    write(root/'etc/kernel-image.sha256',meta['image_sha256']+'\n')
    shutil.copytree(BUILD/'kernel/modules',root/'lib/modules',symlinks=True)
    proot(root,['/bin/busybox','depmod','-a',release])
    output=BUILD/'artifacts'
    output.mkdir(exist_ok=True)
    data = newc(root)
    packed = legacy_lz4(data)
    (output/'initramfs-arm64.cpio.lz4').write_bytes(packed)
    write(output/'initramfs.manifest.json',json.dumps({
        'kernel':meta,'format':'legacy-lz4/newc','uncompressed_bytes':len(data),
        'sha256':digest(output/'initramfs-arm64.cpio.lz4'),
        'root_selection':['DT /chosen/w202,root-partuuid','cmdline root='],
        'early_modules':[], 'hardware_tested':False},indent=2)+'\n')


def rootfs(profile):
    import gzip
    import subprocess
    meta = json.loads((BUILD/'kernel/manifest.json').read_text())
    release = meta['release']
    root = BUILD/profile/'rootfs'
    work = BUILD/profile/'work'
    audit = work/'dpkg-audit.txt'
    if not (work/'configured').exists() or not audit.exists() or audit.stat().st_size:
        raise SystemExit('Rootfs is not fully configured and audited')
    modules = root/'usr/lib/modules'/release
    if not modules.exists():
        shutil.copytree(BUILD/'kernel/modules'/release, modules, symlinks=True)
    write(root/'usr/lib/reimuks/kernel-release',release+'\n')
    write(root/'usr/lib/reimuks/kernel-image.sha256',meta['image_sha256']+'\n')
    write(root/'usr/lib/reimuks/kernel-manifest.json',json.dumps(meta,indent=2)+'\n')
    shutil.copyfile(BUILD/'kernel/Image',root/'boot'/('Image-'+release))
    shutil.copyfile(BUILD/'kernel/config',root/'boot'/('config-'+release))
    write(work/'archive.sh',f'''#!/bin/sh
set -eu
depmod -a {release}
dpkg --audit > /work/dpkg-audit.txt
test ! -s /work/dpkg-audit.txt
tar --numeric-owner --sort=name --one-file-system --xattrs --acls \
 --exclude=./dev/* --exclude=./proc/* --exclude=./sys/* --exclude=./run/* \
 --exclude=./tmp/* --exclude=./host-rootfs --exclude=./packages \
 --exclude=./work --exclude=./output -cf /output/desktop-{profile}-arm64-rootfs.tar -C / .
''',0o755)
    output=BUILD/'artifacts'
    output.mkdir(exist_ok=True)
    proot(root,['/usr/bin/fakeroot-tcp','-i','/work/fakeroot.state',
                '/bin/sh','/work/archive.sh'],[f'{work}:/work',f'{output}:/output'])
    source=output/f'desktop-{profile}-arm64-rootfs.tar'
    dest=source.with_suffix('.tar.gz')
    with source.open('rb') as src, dest.open('wb') as target:
        with gzip.GzipFile(filename='',mode='wb',fileobj=target,mtime=0,compresslevel=6) as gz:
            shutil.copyfileobj(src,gz,1024*1024)
    source.unlink()
    shutil.copyfile(work/'packages.tsv',output/f'{profile}-packages.tsv')
    debs={p.name:digest(p) for p in (BUILD/f'apt-{profile}'/'archives').glob('*.deb')}
    login = {}
    for line in (root/'etc/shadow').read_text().splitlines():
        fields = line.split(':')
        if fields[0] in ('root', 'reimuks'):
            login[fields[0]] = 'locked' if fields[1].startswith(('!', '*')) else 'configured'
    write(output/f'{profile}.manifest.json',json.dumps({
        'profile':'desktop/'+profile,'kernel_flavor':'desktop','suite':'trixie','architecture':'arm64','kernel':meta,
        'packages':debs,'sha256':digest(dest),'hardware_tested':False,
        'credentials':login},indent=2)+'\n')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['import-kernel','initramfs','rootfs'])
    p.add_argument('--profile',choices=['server','kde'],default='server')
    for name in ('image','modules','config','identity'):
        p.add_argument('--'+name,type=Path)
    a=p.parse_args()
    if a.action=='import-kernel':
        if not all((a.image,a.modules,a.config,a.identity)):
            p.error('all four input paths are required')
        import_kernel(a.image,a.modules,a.config,a.identity)
    elif a.action=='initramfs':
        initramfs()
    else:
        rootfs(a.profile)

if __name__=='__main__':
    main()
