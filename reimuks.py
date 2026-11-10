#!/usr/bin/env python3
"""REIMUKS build entry: select a board and one or more output targets."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT/'scripts'))
from boot import boards


def main():
    registry = boards()
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--list-boards', action='store_true')
    p.add_argument('--board', choices=sorted(registry))
    p.add_argument('--target', nargs='+', choices=['uefi','efi','initramfs','rootfs'])
    p.add_argument('--profile', nargs='+', choices=['server','desktop/server','desktop/kde','desktop/gnome','desktop/niri'], default=['desktop/server'])
    p.add_argument('--output', type=Path, help='fresh boot output directory; distro archives remain in build/artifacts')
    p.add_argument('--source-cache', type=Path, default=ROOT/'build/boot-sources')
    p.add_argument('--jobs', type=int, default=4)
    a = p.parse_args()
    if a.list_boards:
        for name, (_, config) in registry.items():
            print(f'{name}: {config["architecture"]}; {", ".join(config["profiles"])}')
        return
    if not a.board or not a.target or a.jobs < 1:
        p.error('provide --board, --target and positive --jobs')
    config = registry[a.board][1]
    placeholders = config.get('placeholders', {})
    pending = [profile for profile in a.profile if profile in placeholders]
    if pending:
        p.error('; '.join(profile+' is a placeholder: '+placeholders[profile] for profile in pending))
    if not set(a.profile).issubset(config['profiles']):
        p.error('profile is unsupported by selected board')
    a.profile = [profile.removeprefix('desktop/') for profile in a.profile]
    targets = set(a.target)
    def run(script, *args):
        subprocess.run([sys.executable,str(ROOT/'scripts'/script),*[str(x) for x in args]],check=True,cwd=ROOT)
    if targets & {'initramfs','rootfs'}:
        manifest = ROOT/'build/kernel/manifest.json'
        if not manifest.is_file():
            p.error('import matching kernel/modules with scripts/pack.py import-kernel first')
        # One imported kernel set per local build tree; no implicit cross-board reuse.
        expected = config.get('kernel_release_suffix')
        if expected and expected not in json.loads(manifest.read_text())['release']:
            p.error('imported kernel does not match selected board')
    if targets & {'uefi','efi'}:
        if not a.output:
            p.error('UEFI/EFI build requires a fresh --output directory')
        stage = 'all' if {'uefi','efi'} <= targets else ('uefi' if 'uefi' in targets else 'efi')
        run('boot.py','build','--board',a.board,'--stage',stage,'--output',a.output,
            '--source-cache',a.source_cache,'--jobs',a.jobs)
        import shutil
        source = a.output.resolve()
        manifest = json.loads((source/'firmware-manifest.json').read_text())
        dest = ROOT/'build/artifacts'/a.board/'boot'
        dest.mkdir(parents=True,exist_ok=True)
        for name in manifest['artifacts']:
            target = dest/name
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(source/name,target)
        # Preserve independent stage manifests when UEFI and EFI are built separately.
        shutil.copy2(source/'firmware-manifest.json',dest/(stage+'-manifest.json'))
        import verify_boot
        verified = verify_boot.verify(dest,stage+'-manifest.json')
        (dest/(stage+'-verification.json')).write_text(json.dumps(verified,indent=2)+'\n')
        print('Boot artifacts: '+str(dest))
    def ensure_rootfs(profile):
        work = ROOT/'build'/profile/'work'
        if not (work/'configured').exists():
            run('build.py','tools')
            run('build.py','fetch','--profile',profile)
            if not (ROOT/'build'/profile/'rootfs').exists():
                run('build.py','assemble','--profile',profile)
            run('build.py','configure','--profile',profile)
    if 'rootfs' in targets:
        for profile in dict.fromkeys(a.profile):
            ensure_rootfs(profile)
            run('pack.py','rootfs','--profile',profile)
    if 'initramfs' in targets:
        ensure_rootfs('server')
        import pack
        old = pack.BUILD/'initramfs'
        # Preserve previous staging trees instead of destroying existing build data.
        if old.exists():
            import time
            old.rename(old.with_name('initramfs-'+str(time.time_ns())))
        pack.initramfs()
    if targets & {'initramfs','rootfs'}:
        import verify
        output = ROOT/'build/artifacts'
        checks = {}
        if 'initramfs' in targets:
            checks['initramfs'] = verify.verify_initramfs(output/'initramfs-arm64.cpio.lz4')
        if 'rootfs' in targets:
            for profile in dict.fromkeys(a.profile):
                checks[profile] = verify.verify_rootfs(output/f'desktop-{profile}-arm64-rootfs.tar.gz',profile)
        (output/f'{a.board}-selected-verification.json').write_text(json.dumps(checks,indent=2)+'\n')
        import hashlib
        files = sorted(output.glob('*rootfs.tar.gz'))+sorted(output.glob('initramfs-*.cpio.lz4'))
        (output/'SHA256SUMS').write_text(''.join(hashlib.sha256(f.read_bytes()).hexdigest()+'  '+f.name+'\n' for f in files))
        print(json.dumps(checks,indent=2))


if __name__ == '__main__':
    main()
