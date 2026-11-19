"""Shared Debian archive tooling. Each App overlay supplies its inputs and policy."""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tarfile

import build
from apt_selection import selected_archives
from distributions import identity, repository_key
from overlay_package import staging
from user_overlay import archive


INSTALLER = r'''#!/bin/sh
set -eu
test "$(id -u)" = 0 || { echo 'Root is required' >&2; exit 1; }
cd "$(dirname "$0")"
test "$(dpkg --print-architecture)" = @ARCH@ || { echo 'Wrong Debian architecture' >&2; exit 1; }
sha256sum --quiet -c SHA256SUMS
offline_apt=$(mktemp -d "${TMPDIR:-/tmp}/reimuks-app.XXXXXX")
trap 'rm -rf -- "$offline_apt"' EXIT
mkdir -p "$offline_apt/lists/partial" "$offline_apt/archives/partial" "$offline_apt/empty"
uri=$(python3 -c 'from pathlib import Path; print(Path.cwd().as_uri())')
printf 'deb [trusted=yes] %s ./\n' "$uri" > "$offline_apt/sources"
apt_local() {
    apt-get -o Dir::Etc::sourcelist="$offline_apt/sources" \
        -o Dir::Etc::sourceparts="$offline_apt/empty" \
        -o Dir::State::lists="$offline_apt/lists" \
        -o Dir::Cache::archives="$offline_apt/archives" \
        -o Dir::Cache::pkgcache="" -o Dir::Cache::srcpkgcache="" "$@"
}
apt_local update
apt_local --simulate --no-remove --no-install-recommends install @PACKAGES@
@BEFORE@
apt_local --no-remove --no-install-recommends -y install @PACKAGES@
@AFTER@
'''


def fields(stanza):
    return dict(line.split(': ', 1) for line in stanza.splitlines()
                if re.match(r'^[^\s:]+: ', line))


def vendor_sources(distribution, repositories, *, target=False):
    lines = []
    for repo in repositories:
        key = repo['target_keyring'] if target else repository_key(distribution, repo)
        lines.append(f'deb [arch={distribution["architecture"]} signed-by={key}] '
                     f'{repo["uri"]} {repo["suite"]} {" ".join(repo["components"])}\n')
    return ''.join(lines)


def debs_from(state, requested, distribution):
    if (state/'status').stat().st_size:
        raise ValueError(f'{state}: expected an empty APT status database')
    architecture = distribution['architecture']
    result = []
    for path in selected_archives(state, requested, architecture=architecture):
        if not re.fullmatch(r'[a-zA-Z0-9_.+~%:-]+\.deb', path.name):
            raise ValueError(f'Invalid Debian archive name: {path.name}')
        control = subprocess.check_output(['dpkg-deb', '-f', path], text=True).strip()
        meta = fields(control)
        result.append((path, control, dict(
            package=meta['Package'], version=meta['Version'], architecture=meta['Architecture'],
            file='packages/'+path.name, sha256=build.digest(path))))
    if set(requested) - {meta['package'] for _, _, meta in result}:
        raise ValueError('APT cache does not contain all requested applications')
    return sorted(result, key=lambda item: item[2]['package'])


def validate_fetched(state, debs):
    """Check even already cached downloads against freshly authenticated indexes."""
    names = [f"{meta['package']}={meta['version']}" for _, _, meta in debs]
    data = subprocess.check_output(['apt-cache', 'show', *names], text=True,
                                   env=dict(os.environ, APT_CONFIG=str(state/'apt.conf'), LC_ALL='C'))
    indexed = {(item.get('Package'), item.get('Version'), item.get('Architecture'), item.get('SHA256'))
               for item in map(fields, data.split('\n\n'))}
    for path, _, meta in debs:
        if (meta['package'], meta['version'], meta['architecture'], meta['sha256']) not in indexed:
            raise ValueError(f'{path.name}: package does not match the authenticated APT index')


def fetch(name, requested, distribution, repositories):
    if not (build.TOOLS/'usr/share/keyrings/debian-archive-keyring.gpg').is_file():
        build.prepare_tools()
    state = build.apt_state('apt-overlay-'+name, distribution['architecture'])
    with (state/'sources.list').open('a') as output:
        output.write(vendor_sources(distribution, repositories))
    build.apt(state, '-o', 'APT::Update::Error-Mode=any', 'update')
    build.apt(state, '--download-only', '--no-install-recommends', '-y', 'install', *requested)
    debs = debs_from(state, requested, distribution)
    validate_fetched(state, debs)
    write_receipt(state, name, requested, distribution, debs)
    return debs


def write_receipt(state, name, requested, distribution, debs):
    build.write(state/'fetch-complete.json', json.dumps(dict(
        distribution=identity(distribution), overlay=name, requested=list(requested),
        archives={path.name: meta['sha256'] for path, _, meta in debs}), indent=2)+'\n')


def cached_debs(state, requested, distribution):
    receipt = json.loads((state/'fetch-complete.json').read_text())
    if receipt['distribution'] != identity(distribution):
        raise ValueError(f'{state}: cache belongs to a different distribution configuration')
    debs = debs_from(state, requested, distribution)
    for path, _, meta in debs:
        if meta['sha256'] != receipt['archives'].get(path.name):
            raise ValueError(f'{path.name}: cached archive is missing from the receipt or changed')
    return debs


def pack(output, name, requested, distribution, debs, repositories=(), files=None, configure=None):
    arch = distribution['architecture']
    manifest = dict(schema=1, id=name, kind='app', aliases=[], distribution=identity(distribution),
                    requested=list(requested), packages=[meta for _, _, meta in debs],
                    board_drivers_included=False)

    def emit(result):
        sums, index = {}, []

        def data(path, content, mode=0o644):
            info = tarfile.TarInfo(path)
            info.size, info.mode = len(content), mode
            result.addfile(info, io.BytesIO(content))
            sums[path] = hashlib.sha256(content).hexdigest()

        data('manifest.json', (json.dumps(manifest, indent=2)+'\n').encode())
        for path, control, meta in debs:
            relative = meta['file']
            info = tarfile.TarInfo(relative)
            info.size = path.stat().st_size
            with path.open('rb') as stream:
                result.addfile(info, stream)
            sums[relative] = meta['sha256']
            index.append(f'{control}\nFilename: {relative}\nSize: {info.size}\nSHA256: {sums[relative]}\n\n')
        data('Packages.gz', gzip.compress(''.join(index).encode(), mtime=0))

        if files:
            for path in sorted(files.rglob('*')):
                if path.is_symlink() or not (path.is_dir() or path.is_file()):
                    raise ValueError(f'Unexpected App overlay file: {path}')
                if path.is_file():
                    data('rootfs/'+path.relative_to(files).as_posix(), path.read_bytes(),
                         path.stat().st_mode & 0o755)
        for repo in repositories:
            data('rootfs'+repo['target_keyring'], repository_key(distribution, repo).read_bytes())
        if repositories:
            data('rootfs/etc/apt/sources.list.d/reimuks-apps.list',
                 vendor_sources(distribution, repositories, target=True).encode())
        before, after = [], []
        if files or repositories:
            before.append('cp -a --no-preserve=ownership rootfs/. /')
        if configure:
            data('configure.py', configure.read_bytes())
            before.append('python3 configure.py')
            after.append('python3 configure.py')
        if repositories:
            after.append('apt-cache policy >/dev/null')
        install = (INSTALLER.replace('@ARCH@', shlex.quote(arch))
                   .replace('@PACKAGES@', shlex.join(requested))
                   .replace('@BEFORE@', '\n'.join(before)).replace('@AFTER@', '\n'.join(after)))
        data('install.sh', install.encode(), 0o755)
        checks = ''.join(f'{digest}  {path}\n' for path, digest in sorted(sums.items()))
        data('SHA256SUMS', checks.encode())

    payload = output/f'{name}-{arch}.tar.gz'
    archive(payload, emit)
    payload.chmod(0o644)
    payload_hash = build.digest(payload)
    manifest_path = output/f'{name}.manifest.json'
    manifest_path.write_text(json.dumps(dict(
        manifest, archive=payload.name, bytes=payload.stat().st_size,
        sha256=payload_hash), indent=2)+'\n')
    (output/'package.json').write_text(json.dumps(dict(
        schema=1, id='apps-'+name, architecture=arch, distribution=distribution['id'],
        requires=['distribution'], files={
            payload.name: payload_hash,
            manifest_path.name: build.digest(manifest_path),
        }), indent=2)+'\n')


def main(name, requested, *, keyrings=(), files=None, configure=None):
    parser = argparse.ArgumentParser(description=f'Build the {name} App overlay')
    parser.add_argument('--distribution', default=os.environ.get('REIMUKS_DISTRIBUTION', build.DEFAULT))
    parser.add_argument('--architecture', help='Must match the selected distribution')
    parser.add_argument('--output', type=Path, help='New package directory; defaults to the shared package pool')
    parser.add_argument('--cache', type=Path, help='Build offline from an authenticated APT state')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--offline', action='store_true', help='Require the existing APT cache')
    mode.add_argument('--refresh', action='store_true', help='Refresh packages from the selected distribution repositories')
    args = parser.parse_args()
    if args.cache and args.refresh:
        parser.error('--cache cannot be used with --refresh')
    os.umask(0o022)
    try:
        build.select_distribution(args.distribution)
        distribution = build.DISTRIBUTION
        arch = distribution['architecture']
        if args.architecture and args.architecture != arch:
            raise ValueError(f'{args.distribution} packages are {arch}, not {args.architecture}')
        available = {item['target_keyring']: item
                     for item in distribution.get('additional_packages', {}).get('repositories', [])}
        if missing := set(keyrings)-available.keys():
            raise ValueError('Missing repository configuration: '+', '.join(sorted(missing)))
        repositories = [available[key] for key in keyrings]
        pool = Path(os.environ.get('REIMUKS_PACKAGE_ROOT', build.SHARED_BUILD/'packages'))
        output = args.output or pool/'apps'/args.distribution/arch/name
        state = (args.cache or build.package_cache('apt-overlay-'+name)).expanduser().resolve()
        with staging(output) as (_, export):
            if args.offline or args.cache or (not args.refresh and (state/'fetch-complete.json').is_file()):
                debs = cached_debs(state, requested, distribution)
            else:
                debs = fetch(name, requested, distribution, repositories)
            pack(export, name, requested, distribution, debs, repositories, files, configure)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'{name}: {error}\n')
    print(output)
