#!/usr/bin/env python3
"""REIMUKS build entry: select a board and one or more output targets."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import os

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT/'scripts'))
from boot import boards
from distributions import DEFAULT, distributions, load_distribution, resolve_profile, identity
from output_paths import build_root, board_root, boot_paths, shared_root, temporary_environment


def main():
    registry = boards()
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--list-boards', action='store_true')
    p.add_argument('--list-distributions', action='store_true')
    p.add_argument('--distribution', choices=sorted(distributions()), help='rootfs only; default: debian/trixie')
    p.add_argument('--board', choices=sorted(registry))
    p.add_argument('--preset', metavar='NAME', help='Build a named preset for the selected board')
    p.add_argument('--clean', action='store_true',
                   help='replace a rootfs preset\'s default output; keep shared layers and downloads')
    p.add_argument('--target', nargs='+', choices=['kernel','userspace','kernel-runtime','uefi','efi','esp','initramfs','rootfs','compose'])
    p.add_argument('--esp-tree', type=Path, help='explicit ESP file tree; no GPT input')
    p.add_argument('--esp-size-mib', type=int, help='ESP filesystem image capacity')
    p.add_argument('--esp-tools', type=Path, help='native dosfstools/mtools directory')
    p.add_argument('--profile', nargs='+', choices=['server','desktop/server','desktop/kde','desktop/gnome','desktop/niri'], help='rootfs/userspace scenario; default: desktop/server')
    p.add_argument('--output', type=Path, help='boot artifact directory or explicit preset output archive')
    p.add_argument('--compose-config', type=Path, help='ordered layer recipe JSON for compose or rootfs')
    p.add_argument('--package-root', type=Path, help='published layer receipts and packages, default: <shared-build>/packages')
    p.add_argument('--user-input-root', type=Path, metavar='DIR',
                   help='build named user overlays from this private input directory')
    p.add_argument('--build-root', type=Path, help='board work trees and artifacts; default: build/boards/<board> (shared packages stay in build/)')
    p.add_argument('--source-cache', type=Path, help='boot source cache; defaults to the selected boot build tree')
    p.add_argument('--jobs', type=int, default=4)
    p.add_argument('--boot-inputs', type=Path, help='UEFI partition packaging inputs; defaults to the board-local config')
    p.add_argument('--app-overlay', action='append', metavar='GROUP',
                   help='add an application group to a preset (repeatable)')
    p.add_argument('--user-overlay', action='append', metavar='LAYER',
                   help='compose: add ID, ID=SOURCE, or a package receipt path (repeatable); '
                        'rootfs: a private files directory')
    p.add_argument('--base-only', action='store_true', help='rootfs/server only; generic base without board or DE packages')
    p.add_argument('--from-base', action='store_true', help='rootfs only; compose a desktop onto the configured server base')
    p.add_argument('--de-cache', type=Path, help='rootfs --from-base; authenticated offline desktop dependency cache')
    p.add_argument('--kernel-profile', default='desktop')
    p.add_argument('--build-config', type=Path, help='board integration SDK/compiler configuration')
    p.add_argument('--plan', action='store_true', help='show the selected stages without building')
    p.add_argument('--accounts', type=Path, help='rootfs only; desktop root/reimuks account configuration')
    a = p.parse_args()
    if a.list_distributions:
        for name in distributions():
            distro = load_distribution(name)
            print(f'{name}: {distro["name"]}; {distro["architecture"]}; {", ".join(distro["profiles"])}')
        return
    if a.list_boards:
        for name, (_, config) in registry.items():
            print(f'{name}: {config["architecture"]}; {", ".join(config["profiles"])}')
        return
    from compose_target import identifier, recipe
    if a.preset is not None:
        if not a.board or a.compose_config is not None:
            p.error('--preset needs --board and replaces --compose-config')
        try:
            name = identifier(a.preset, 'preset')
            a.compose_config = registry[a.board][0]/'targets'/f'{name}.json'
            preset = recipe(a.compose_config)
        except (OSError, ValueError) as error:
            p.error(f'Cannot load preset {a.preset}: {error}')
        if a.target is None:
            a.target = ['rootfs' if 'rootfs' in preset else 'compose']
    if a.clean and (a.target != ['rootfs'] or not a.preset or a.output is not None):
        p.error('--clean requires a rootfs preset with its default output')
    if a.compose_config is not None or (a.target and 'compose' in a.target):
        if a.target not in (['compose'], ['rootfs']) or a.compose_config is None:
            p.error('Select exactly one of compose or rootfs with a recipe')
        if any((a.distribution, a.profile, a.accounts, a.esp_tree, a.esp_size_mib is not None,
                a.esp_tools, a.source_cache, a.boot_inputs, a.base_only,
                a.from_base, a.de_cache, a.build_config)):
            p.error('Use the recipe and overlay options for a preset')
        pool = a.package_root or shared_root()/'packages'
        options = dict(board=a.board, plan=a.plan, app_overlays=a.app_overlay or (),
                       user_overlays=a.user_overlay or (), user_input_root=a.user_input_root)
        try:
            target = recipe(a.compose_config)
            work = (a.build_root or build_root(a.board or target.get('board'))).expanduser().resolve()
            if a.build_root:
                os.environ['REIMUKS_BUILD_ROOT'] = str(work.expanduser().resolve())
            if a.target == ['rootfs']:
                from rootfs_target import assemble
                output = a.output or work/'artifacts/targets'/f'{target["id"]}-rootfs.tar.gz'
                if not a.plan:
                    os.environ.update(temporary_environment(work))
                result = assemble(a.compose_config, pool, output, device_root=work, clean=a.clean, **options)
            else:
                from compose_target import assemble
                output = a.output
                if output is None and a.preset is not None and not a.plan:
                    output = work/'artifacts/targets'/f'{target["id"]}.tar'
                if not a.plan and output is None:
                    p.error('--target compose requires --output unless using --preset')
                result = assemble(a.compose_config, pool, output, **options)
        except (OSError, ValueError, subprocess.CalledProcessError) as error:
            p.exit(1, f'{p.prog}: {error}\n')
        print(json.dumps(result, indent=2))
        return
    if a.app_overlay or a.package_root is not None or a.user_input_root is not None:
        p.error('Application and package inputs require a preset or compose recipe')
    if not a.board or not a.target or a.jobs < 1:
        p.error('provide --board, --target and positive --jobs')
    directory, config = registry[a.board]
    targets = set(a.target)
    if (a.base_only or a.from_base or a.de_cache) and 'rootfs' not in targets:
        p.error('Layer composition options require --target rootfs')
    if a.de_cache and not a.from_base:
        p.error('--de-cache requires --from-base')
    if 'esp' in targets:
        if not a.esp_tree or a.esp_size_mib is None:
            p.error('--target esp requires --esp-tree and --esp-size-mib')
        if not a.esp_tree.is_dir() or not 32 <= a.esp_size_mib <= 2048*1024:
            p.error('ESP tree must exist and capacity must be between 32 MiB and 2 TiB')
    elif any(v is not None for v in (a.esp_tree, a.esp_size_mib, a.esp_tools)):
        p.error('--esp-* options require --target esp')
    supported = config.get('supported_targets')
    if supported is not None and not targets.issubset(supported):
        p.error(config.get('unavailable_reason', 'selected board targets are not implemented'))
    if not targets & {'rootfs', 'userspace'} and (a.distribution is not None or a.profile is not None or a.accounts is not None):
        p.error('--distribution, --profile and --accounts apply only to --target rootfs/userspace')
    if a.user_overlay:
        if 'rootfs' not in targets:
            p.error('--user-overlay requires --target rootfs or compose')
        if len(a.user_overlay) != 1:
            p.error('--target rootfs accepts one --user-overlay directory; compose accepts multiple layers')
        a.user_overlay = Path(a.user_overlay[0])
    if a.user_overlay is not None and not a.user_overlay.is_dir():
        p.error('--user-overlay must be a directory of private user files')
    if a.user_overlay is not None and a.base_only:
        p.error('--user-overlay cannot be combined with --base-only')
    if a.boot_inputs is not None and 'uefi' not in targets:
        p.error('--boot-inputs applies only to --target uefi')
    distribution = None
    if targets & {'rootfs', 'userspace'}:
        a.distribution = a.distribution or DEFAULT
        a.profile = a.profile or ['desktop/server']
        placeholders = config.get('placeholders', {})
        pending = [profile for profile in a.profile if profile in placeholders]
        if pending:
            p.error('; '.join(profile+' is a placeholder: '+placeholders[profile] for profile in pending))
        if not set(a.profile).issubset(config['profiles']):
            p.error('profile is unsupported by selected board')
        try:
            distribution = load_distribution(a.distribution)
            if distribution['architecture'] != config['architecture']:
                p.error('distribution architecture differs from selected board')
            for profile in a.profile:
                resolve_profile(profile, distribution)
        except ValueError as error:
            p.error(str(error))
        a.profile = [profile.removeprefix('desktop/') for profile in a.profile]
        if a.base_only and (a.profile != ['server'] or a.from_base):
            p.error('--base-only requires only desktop/server and cannot combine with --from-base')
        if a.from_base and not set(a.profile).issubset({'kde', 'gnome'}):
            p.error('--from-base requires KDE or GNOME')
    os.environ['REIMUKS_BOARD'] = a.board
    os.environ['REIMUKS_DISTRIBUTION'] = a.distribution or DEFAULT
    if a.build_root:
        os.environ['REIMUKS_BUILD_ROOT'] = str(a.build_root.expanduser().resolve())
    boot_work, boot_artifacts, boot_cache = boot_paths(a.board)
    a.source_cache = a.source_cache or boot_cache
    if a.plan:
        print(json.dumps({'board': a.board, 'targets': [t for t in ['kernel', 'userspace', 'uefi', 'efi', 'kernel-runtime', 'rootfs', 'initramfs', 'esp'] if t in targets], 'profiles': a.profile, 'rootfs_requires_kernel': False, 'base_only':a.base_only, 'from_base':a.from_base, 'esp_tree': str(a.esp_tree) if a.esp_tree else None, 'esp_size_mib': a.esp_size_mib, 'shared_build': str(shared_root()), 'distribution_build': str(shared_root()/'distributions'/(a.distribution or DEFAULT)/config['architecture']), 'build_root': str(build_root(a.board)), 'boot_work': str(boot_work), 'boot_output': str(a.output or boot_artifacts), 'source_cache': str(a.source_cache)}, indent=2))
        return
    os.environ.update(temporary_environment(build_root(a.board)))
    if targets & {'initramfs', 'rootfs', 'kernel', 'kernel-runtime'}:
        os.environ['REIMUKS_BOARD'] = a.board
        os.environ['REIMUKS_DISTRIBUTION'] = a.distribution or DEFAULT
        import build as backend
        backend.select_board(a.board)
        backend.select_distribution(a.distribution or DEFAULT)
    def run(script, *args):
        subprocess.run([sys.executable,str(ROOT/'scripts'/script),*[str(x) for x in args]],check=True,cwd=ROOT)
    if 'kernel' in targets:
        if not a.kernel_profile.isidentifier():
            p.error('invalid kernel profile')
        run('kernel.py', '--board', a.board, '--profile', a.kernel_profile, '--jobs', a.jobs)
        exporter = (directory/config['kernel_exporter']).resolve()
        subprocess.run([sys.executable, str(exporter), '--profile', a.kernel_profile], check=True)
        runtime = directory/config['kernel_runtime'].format(profile=a.kernel_profile)
        meta = json.loads((runtime/'identity.json').read_text())
        run('pack.py', 'import-kernel', '--board', a.board, '--image', runtime/'Image',
            '--config', runtime/'config', '--identity', runtime/'identity.json',
            '--modules', runtime/'modules'/meta['release'])
    if 'userspace' in targets:
        builder = (directory/config['integration_builder']).resolve()
        allowed_builders = (directory.resolve(), (ROOT/'scripts').resolve())
        if not any(builder.is_relative_to(root) for root in allowed_builders):
            p.error('integration builder must belong to the board or shared scripts')
        for profile in dict.fromkeys(a.profile):
            arguments = ['--profile', profile]
            if a.build_config:
                arguments += ['--config', str(a.build_config.resolve())]
            subprocess.run([sys.executable, str(builder), *arguments], check=True)
    if 'kernel-runtime' in targets:
        run('pack.py', 'kernel-runtime', '--board', a.board)
    if 'initramfs' in targets:
        manifest = backend.kernel_directory()/'manifest.json'
        if not manifest.is_file():
            p.error('import matching kernel/modules with scripts/pack.py import-kernel first')
        # One imported kernel set per local build tree; no implicit cross-board reuse.
        expected = config.get('kernel_release_suffix')
        if expected and expected not in json.loads(manifest.read_text())['release']:
            p.error('imported kernel does not match selected board')
    if targets & {'uefi','efi'}:
        stage = 'all' if {'uefi','efi'} <= targets else ('uefi' if 'uefi' in targets else 'efi')
        boot_args = ['build','--board',a.board,'--stage',stage,
                     '--source-cache',a.source_cache,'--jobs',a.jobs]
        if a.output:
            boot_args += ['--output', a.output]
        if a.boot_inputs:
            boot_args += ['--inputs', a.boot_inputs]
        run('boot.py', *boot_args)
    if 'esp' in targets:
        esp_args = ['--tree', a.esp_tree.resolve(), '--size-mib', a.esp_size_mib,
                    '--output', board_root(a.board)/'artifacts/esp.img']
        if a.esp_tools:
            esp_args += ['--tools', a.esp_tools.resolve()]
        run('esp.py', *esp_args)
    def ensure_rootfs(profile, apply_account_config=False):
        with backend.profile_lock(profile):
            work = backend.profile_directory(profile)/'work'
            account_args = ['--accounts', str(a.accounts.resolve())] if apply_account_config and a.accounts is not None else []
            if (work/'configured').exists():
                backend.check_rootfs(profile)
                if apply_account_config and (a.accounts is not None or (ROOT/'config/accounts.local.json').exists()):
                    run('build.py','accounts','--profile',profile,*account_args)
            if not (work/'configured').exists():
                run('build.py','tools')
                run('build.py','fetch','--profile',profile)
                if not (backend.profile_directory(profile)/'rootfs').exists():
                    run('build.py','assemble','--profile',profile)
                run('build.py','configure','--profile',profile,*account_args)
    checks_by_output = {}
    if 'rootfs' in targets:
        import verify
        output = backend.shared_distribution()/'artifacts' if a.base_only else backend.artifact_directory()
        checks = checks_by_output.setdefault(output, {'distribution': identity(distribution)})
        overlay_archive = None
        if a.user_overlay is not None:
            overlay_archive = output/'user-overlay.tar.gz'
            run('user_overlay.py', 'pack', '--source', a.user_overlay.resolve(),
                '--output', overlay_archive)
        for profile in dict.fromkeys(a.profile):
            ensure_rootfs('server' if a.from_base else profile, apply_account_config=True)
            if not a.base_only:
                import layers
                layers.fetch_board(profile)
            arguments = ['--profile',profile]
            if a.base_only:
                arguments += ['--base-only']
            if a.from_base:
                arguments += ['--from-base']
            if a.de_cache:
                arguments += ['--de-cache',a.de_cache.resolve()]
            run('pack.py','rootfs',*arguments)
            label = 'base' if a.base_only else profile
            base_archive = output/f'desktop-{label}-arm64-rootfs.tar.gz'
            checks[label] = verify.verify_rootfs(base_archive,profile,a.base_only)
            if overlay_archive is not None:
                deployment = output/f'desktop-{label}-arm64-deployment.tar.gz'
                run('user_overlay.py', 'merge', '--base', base_archive,
                    '--overlay', overlay_archive, '--output', deployment)
                checks[f'{label}_deployment'] = {
                    'bytes': deployment.stat().st_size,
                    'sha256': verify.digest(deployment),
                    'user_overlay': overlay_archive.name,
                }
    if 'initramfs' in targets:
        # The board initramfs is independent of the selected rootfs distro/DE.
        os.environ['REIMUKS_DISTRIBUTION'] = DEFAULT
        backend.select_distribution(DEFAULT)
        run('build.py', 'tools')
        run('runtime_tools.py', '--board', a.board)
        import pack
        import verify
        pack.initramfs(config.get('initramfs_early_modules', []))
        output = backend.artifact_directory()
        checks = checks_by_output.setdefault(output, {})
        checks['initramfs'] = verify.verify_initramfs(output/'initramfs-arm64.cpio.lz4')
    for output, checks in checks_by_output.items():
        (output/('distribution-selected-verification.json' if a.base_only else f'{a.board}-selected-verification.json')).write_text(json.dumps(checks,indent=2)+'\n')
        import hashlib
        files = (sorted(output.glob('*rootfs.tar.gz'))+
                 sorted(output.glob('initramfs-*.cpio.lz4'))+
                 sorted(output.glob('user-overlay.tar.gz'))+
                 sorted(output.glob('*deployment.tar.gz')))
        (output/'SHA256SUMS').write_text(''.join(hashlib.sha256(f.read_bytes()).hexdigest()+'  '+f.name+'\n' for f in files))
        print(json.dumps(checks,indent=2))


if __name__ == '__main__':
    main()
