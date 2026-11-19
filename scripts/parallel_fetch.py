"""Populate an APT cache concurrently using hashes from authenticated indexes."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
from pathlib import Path
import shlex
import subprocess
from urllib.parse import unquote, urlsplit


def prefetch(state, packages, workers=6, proxy=None, install_recommends=False):
    env = dict(os.environ, APT_CONFIG=str(state/'apt.conf'))
    plan = subprocess.check_output([
        'apt-get', '-o', 'Debug::NoLocking=true', '--print-uris',
        '--download-only', '--install-recommends' if install_recommends else '--no-install-recommends', '-y', 'install',
        *packages], env=env, text=True)
    records = [shlex.split(line) for line in plan.splitlines() if line.startswith("'")]
    names = sorted({record[1].split('_', 1)[0] for record in records})
    if not names:
        return
    metadata = subprocess.check_output(['apt-cache', 'show', *names], env=env, text=True)
    hashes = {}
    for block in metadata.split('\n\n'):
        fields = dict(line.split(': ', 1) for line in block.splitlines()
                      if ': ' in line and not line.startswith(' '))
        if 'Filename' in fields and 'SHA256' in fields:
            hashes[unquote(fields['Filename'].rsplit('/', 1)[-1])] = fields['SHA256']
    archive = state/'archives'
    temporary = archive/'parallel'
    temporary.mkdir(parents=True, exist_ok=True)

    def download(record):
        if len(record) not in (3, 4):
            raise ValueError("Invalid APT download record")
        uri, filename, size = record[:3]
        if Path(filename).name != filename or urlsplit(uri).scheme not in ('http', 'https'):
            raise ValueError('Unsafe package download record')
        expected = hashes.get(unquote(urlsplit(uri).path.rsplit('/', 1)[-1]))
        if not expected or len(expected) != 64:
            raise ValueError('No authenticated SHA256 for '+filename)
        target = archive/filename
        def valid(path):
            if not path.is_file() or path.stat().st_size != int(size):
                return False
            with path.open('rb') as stream:
                return hashlib.file_digest(stream, 'sha256').hexdigest() == expected
        if valid(target):
            return
        # Coexist with an APT fetch already transferring this particular file.
        if (archive/'partial'/filename).exists():
            return
        partial = temporary/(filename+'.part')
        command = ['curl', *shlex.split(os.environ.get('REIMUKS_CURL_ARGS', '')), '--fail', '--location', '--connect-timeout', '15',
                   '--max-time', '1800', '--retry', '0', '--continue-at', '-', '--silent', '--show-error']
        if proxy:
            command += ['--noproxy', '', '--proxy', proxy]
        # Start a fresh curl process for each retry, so -C - recomputes the
        # offset after a timeout. curl's internal retry restores the original
        # output offset and can discard progress made during a long attempt.
        for attempt in range(4):
            result = subprocess.run([*command, '--output', str(partial), uri])
            if result.returncode == 0:
                break
            if attempt == 3:
                result.check_returncode()
        if not valid(partial):
            partial.unlink(missing_ok=True)
            raise ValueError('Package length/SHA256 mismatch: '+filename)
        partial.replace(target)
        print('Cached '+filename, flush=True)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(download, records))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=6)
    parser.add_argument('--install-recommends', action='store_true')
    parser.add_argument('packages', nargs='+')
    args = parser.parse_args()
    if not 1 <= args.workers <= 16:
        parser.error('workers must be between 1 and 16')
    prefetch(args.state.resolve(), args.packages, args.workers,
             os.environ.get('REIMUKS_DOWNLOAD_PROXY'), args.install_recommends)
