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
import tarfile
from build import BUILD, REPO, digest, write, proot
import build as backend
from distributions import identity
from fakeroot_state import snapshot, reconcile
from startup_preflight import verify as verify_startup
from board_userspace import install_template
from board_userspace import prepare_rootfs as prepare_board_rootfs
from board_userspace import install_rootfs as install_board_rootfs, install_initramfs as install_board_initramfs


def validate_kernel_config(config_text):
    policy = json.loads((backend.board_directory()/'board.json').read_text()).get('kernel_policy', {})
    for symbol in policy.get('forbidden_configs', []):
        if re.search(r'^'+re.escape(symbol)+r'=(?:y|m)$', config_text, re.MULTILINE):
            raise SystemExit('Selected board requires a kernel without '+symbol)
    match = re.search(r'^CONFIG_CMDLINE="(.*)"$', config_text, re.MULTILINE)
    if match:
        args = match.group(1).split()
        rdinit = next((arg for arg in args if arg.startswith('rdinit=')), None)
        if (rdinit is not None and rdinit != 'rdinit=/init') or any(
                arg.startswith(prefix) for prefix in policy.get('forbidden_cmdline_prefixes', []) for arg in args):
            raise SystemExit('Selected board requires a normal initramfs kernel')


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
    config_text = config.read_text()
    validate_kernel_config(config_text)
    if 'CONFIG_RD_LZ4=y' not in config_text:
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
    board_config = json.loads((backend.board_directory()/'board.json').read_text())
    expected_suffix = board_config.get('kernel_release_suffix')
    if meta.get('board', backend.BOARD) != backend.BOARD or (expected_suffix and expected_suffix not in release):
        raise SystemExit('Kernel identity does not match selected board')
    target = backend.kernel_directory()
    if any(path.resolve().is_relative_to(target.resolve()) for path in (image, modules, config, identity)):
        raise ValueError('Kernel import inputs must be outside the import directory')
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    shutil.copyfile(image, target / 'Image')
    shutil.copyfile(config, target / 'config')
    shutil.copytree(modules, target / 'modules' / release, symlinks=True)
    for name in ('build', 'source'):
        p = target / 'modules' / release / name
        if p.is_symlink():
            p.unlink()
    meta.update(board=backend.BOARD, module_hashes=hashes, vermagic=sorted(vermagics),
                inputs={k: p.name for k,p in
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


def initramfs(early_modules=(), output=None):
    meta = json.loads((backend.kernel_directory()/'manifest.json').read_text())
    validate_kernel_config((backend.kernel_directory()/'config').read_text())
    release = meta['release']
    early_modules = list(dict.fromkeys(early_modules))
    available = {p.stem.replace('-', '_') for p in (backend.kernel_directory()/'modules'/release).rglob('*.ko')}
    for name in early_modules:
        if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_-]*', name) or name.replace('-', '_') not in available:
            raise ValueError(f'Early module is absent from the matched kernel set: {name}')
    root = output/'root' if output is not None else backend.distribution_build()/'initramfs/root'
    if root.is_symlink():
        raise SystemExit(f'Initramfs work directory must not be a symlink: {root}')
    if root.exists():
        shutil.rmtree(root)
    for d in ('bin','sbin','lib','etc','dev','proc','sys','run','newroot'):
        (root/d).mkdir(parents=True,exist_ok=True)
    server = backend.board_build()/'initramfs-tools/root'
    if not (server/'usr/bin/busybox').is_file():
        raise ValueError('Prepare initramfs tools with scripts/runtime_tools.py first')
    shutil.copyfile(server/'usr/bin/busybox',root/'bin/busybox')
    (root/'bin/busybox').chmod(0o755)
    for app in ('sh','mount','cat','grep','ln','ip','tr','wc','tail','od','modprobe','mdev','sleep','uname','mkdir','switch_root','setsid','cttyhack','reboot'):
        (root/'bin'/app).symlink_to('busybox')
    shutil.copyfile(server/'usr/sbin/blkid',root/'sbin/blkid')
    (root/'sbin/blkid').chmod(0o755)
    for name in ('libblkid.so.1','libc.so.6','ld-linux-aarch64.so.1'):
        shutil.copyfile(server/'usr/lib/aarch64-linux-gnu'/name,root/'lib'/name)
        (root/'lib'/name).chmod(0o755)
    shutil.copyfile(REPO/'initramfs/init',root/'init')
    (root/'init').chmod(0o755)
    install_board_initramfs(root, backend.board_directory())
    write(root/'etc/early-modules',''.join(name+'\n' for name in early_modules))
    write(root/'etc/kernel-image.sha256',meta['image_sha256']+'\n')
    write(root/'etc/distribution.json',json.dumps(identity(backend.DISTRIBUTION),indent=2)+'\n')
    shutil.copytree(backend.kernel_directory()/'modules',root/'lib/modules',symlinks=True)
    proot(root,['/bin/busybox','depmod','-a',release])
    output=output if output is not None else backend.artifact_directory()
    output.mkdir(parents=True, exist_ok=True)
    data = newc(root)
    packed = legacy_lz4(data)
    (output/'initramfs-arm64.cpio.lz4').write_bytes(packed)
    write(output/'initramfs.manifest.json',json.dumps({
        'distribution':identity(backend.DISTRIBUTION),
        'kernel':meta,'format':'legacy-lz4/newc','uncompressed_bytes':len(data),
        'sha256':digest(output/'initramfs-arm64.cpio.lz4'),
        'root_selection':json.loads((backend.board_directory()/'board.json').read_text()).get('kernel_policy', {}).get('root_selection', ['cmdline root=']),
        'early_modules':early_modules, 'hardware_tested':False},indent=2)+'\n')


def rootfs(profile, user_overlay=None):
    import subprocess
    backend.check_rootfs(profile)
    root = backend.profile_directory(profile)/'rootfs'
    work = backend.profile_directory(profile)/'work'
    audit = work/'dpkg-audit.txt'
    if not (work/'configured').exists() or not audit.exists() or audit.stat().st_size:
        raise SystemExit('Rootfs is not fully configured and audited')
    write(root/'usr/lib/reimuks/distribution.json',json.dumps(identity(backend.DISTRIBUTION),indent=2)+'\n')
    before = snapshot(root)
    backend.configure_locale(profile, root)
    install_board_rootfs(root, profile, backend.board_directory())
    prepare_board_rootfs(root, backend.board_directory(), profile)
    if user_overlay is not None:
        install_template(root, user_overlay.resolve())
    (work/'startup-preflight.json').unlink(missing_ok=True)
    report = verify_startup(root, profile, proot)
    write(work/'startup-preflight.json', json.dumps(report, indent=2)+'\n')
    write(root/'usr/lib/reimuks/startup-preflight.json', json.dumps(report, indent=2)+'\n')
    saved = work/'fakeroot.state'
    archive_state = work/'archive-fakeroot.state'
    if saved.exists():
        reconcile(saved, archive_state, root, before)
    write(work/'archive.sh',f'''#!/bin/sh
set -eu
systemd-sysusers
cp -an /etc/skel/. /home/reimuks/
chown -R reimuks:reimuks /home/reimuks
dpkg --audit > /work/dpkg-audit.txt
test ! -s /work/dpkg-audit.txt
tar --numeric-owner --sort=name --one-file-system --xattrs --acls \
 --exclude=./dev/* --exclude=./proc/* --exclude=./sys/* --exclude=./run/* \
 --exclude=./tmp/* --exclude=./host-rootfs --exclude=./packages \
 --exclude=./usr/lib/modules --exclude=./lib/modules \
 --exclude=./boot/Image-* --exclude=./boot/config-* \
 --exclude=./usr/lib/reimuks/kernel-release --exclude=./usr/lib/reimuks/kernel-image.sha256 \
 --exclude=./usr/lib/reimuks/kernel-manifest.json \
 --exclude=./work --exclude=./output -I "gzip -n -6" -cf /output/desktop-{profile}-arm64-rootfs.tar.gz.part -C / .
''',0o755)
    output=backend.artifact_directory()
    output.mkdir(parents=True, exist_ok=True)
    proot(root,['/usr/bin/fakeroot-tcp','-i','/work/archive-fakeroot.state',
                '/bin/sh','/work/archive.sh'],[f'{work}:/work',f'{output}:/output'])
    dest=output/f'desktop-{profile}-arm64-rootfs.tar.gz'
    partial=dest.with_suffix(dest.suffix+'.part')
    partial.replace(dest)
    shutil.copyfile(work/'packages.tsv',output/f'{profile}-packages.tsv')
    debs={p.name:digest(p) for p in (backend.distribution_build()/f'apt-{profile}'/'archives').glob('*.deb')}
    login = {}
    for line in (root/'etc/shadow').read_text().splitlines():
        fields = line.split(':')
        if fields[0] in ('root', 'reimuks'):
            login[fields[0]] = 'locked' if fields[1].startswith(('!', '*')) else 'configured'
    write(output/f'{profile}.manifest.json',json.dumps({
        'profile':'desktop/'+profile,
        'distribution':identity(backend.DISTRIBUTION),
        'suite':backend.DISTRIBUTION['suite'],'architecture':backend.DISTRIBUTION['architecture'],'kernel_independent':True,
        'packages':debs,'sha256':digest(dest),'hardware_tested':False,
        'credentials':login, 'startup_preflight':report},indent=2)+'\n')


def kernel_runtime():
    """Package a matched kernel runtime separately from distro rootfs."""
    source = backend.kernel_directory()
    meta = json.loads((source / 'manifest.json').read_text())
    release = meta['release']
    if Path(release).name != release or release in ('.', '..'):
        raise ValueError('Invalid kernel release')
    for key, filename in [('image_sha256', 'Image'), ('config_sha256', 'config')]:
        if digest(source / filename) != meta[key]:
            raise ValueError('Kernel input changed: ' + filename)
    modules = source / 'modules' / release
    hashes = {str(p.relative_to(modules)): digest(p) for p in sorted(modules.rglob('*.ko'))}
    if hashes != meta['module_hashes']:
        raise ValueError('Kernel module set or hashes changed')
    config = json.loads((backend.board_directory()/'board.json').read_text())
    for name, parameters in config.get('module_requirements', {}).items():
        matches = list(modules.rglob(name))
        if len(matches) != 1:
            raise ValueError('Missing or ambiguous required module: ' + name)
        data = matches[0].read_bytes()
        for parameter in parameters:
            if b'parmtype='+parameter.encode()+b':' not in data:
                raise ValueError(f'Module {name} does not support parameter {parameter}')
    output = backend.artifact_directory()
    output.mkdir(parents=True, exist_ok=True)
    staging = backend.board_build() / 'kernel-runtime/root'
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    shutil.copytree(modules, staging/'usr/lib/modules'/release, symlinks=True)
    for name in ('build', 'source'):
        (staging/'usr/lib/modules'/release/name).unlink(missing_ok=True)
    write(staging/'usr/lib/reimuks/kernel-release', release+'\n')
    write(staging/'usr/lib/reimuks/kernel-image.sha256', meta['image_sha256']+'\n')
    write(staging/'usr/lib/reimuks/kernel-manifest.json', json.dumps(meta, indent=2)+'\n')
    (staging/'boot').mkdir()
    shutil.copyfile(source/'Image', staging/'boot'/('Image-'+release))
    shutil.copyfile(source/'config', staging/'boot'/('config-'+release))
    checks = [*sorted((staging/'usr/lib/modules'/release).rglob('*.ko')),
              staging/'boot'/('Image-'+release), staging/'boot'/('config-'+release)]
    write(staging/'usr/lib/reimuks/kernel-files.sha256', ''.join(
        digest(path)+'  '+str(path.relative_to(staging))+'\n' for path in checks))
    archive = output / 'kernel-runtime-arm64.tar.gz'
    partial = archive.with_suffix('.gz.part')
    with tarfile.open(partial, 'w:gz') as stream:
        for path in sorted(staging.rglob('*')):
            record = stream.gettarinfo(str(path), arcname=str(path.relative_to(staging)))
            record.uid = record.gid = 0
            record.uname = record.gname = 'root'
            record.mtime = 0
            if record.isfile():
                with path.open('rb') as data:
                    stream.addfile(record, data)
            else:
                stream.addfile(record)
    partial.replace(archive)
    write(output/'kernel-runtime.manifest.json', json.dumps({
        'schema': 1, 'board': backend.BOARD, 'release': release,
        'image_sha256': meta['image_sha256'], 'module_hashes': hashes,
        'sha256': digest(archive), 'after_install': ['depmod -a '+release]}, indent=2)+'\n')
    return archive


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['import-kernel','initramfs','rootfs','kernel-runtime'])
    p.add_argument('--profile',choices=['server','kde','gnome'],default='server')
    p.add_argument('--board', default=os.environ.get('REIMUKS_BOARD', 'w202ds'))
    p.add_argument('--distribution',help='rootfs only; default: debian/trixie')
    p.add_argument('--user-overlay', type=Path, help='rootfs only; explicit private user resources')
    p.add_argument('--early-module', action='append', default=[], help='initramfs only; matched module to load before mounting root')
    p.add_argument('--output', type=Path, help='initramfs only; reusable output directory containing root/ and the archive')
    for name in ('image','modules','config','identity'):
        p.add_argument('--'+name,type=Path)
    a=p.parse_args()
    if a.action != 'rootfs' and a.distribution is not None:
        p.error('--distribution applies only to rootfs')
    if a.action != 'initramfs' and (a.early_module or a.output is not None):
        p.error('--early-module and --output apply only to initramfs')
    backend.select_board(a.board)
    backend.select_distribution((a.distribution or os.environ.get('REIMUKS_DISTRIBUTION', backend.DEFAULT))
                                if a.action == 'rootfs' else backend.DEFAULT)
    if a.action=='import-kernel':
        if not all((a.image,a.modules,a.config,a.identity)):
            p.error('all four input paths are required')
        import_kernel(a.image,a.modules,a.config,a.identity)
    elif a.action=='initramfs':
        initramfs(a.early_module, a.output)
    elif a.action=='kernel-runtime':
        print(kernel_runtime())
    else:
        rootfs(a.profile, a.user_overlay)

if __name__=='__main__':
    main()
