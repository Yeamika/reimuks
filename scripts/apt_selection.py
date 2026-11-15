"""Resolve the exact cached archive set without installing packages."""
import os
import re
import subprocess


def selected_archives(state, requested, recommends=False, architecture='arm64'):
    env = dict(os.environ, APT_CONFIG=str(state/'apt.conf'), LC_ALL='C')
    plan = subprocess.check_output(['apt-get', '--simulate', '--install-recommends' if recommends else '--no-install-recommends',
                                    '-y', 'install', *requested], env=env, text=True)
    wanted = set()
    for line in plan.splitlines():
        if line.startswith('Inst '):
            match = re.match(r'Inst ([^ :]+)(?::\S+)?(?: \[[^]]+\])? \((\S+)', line)
            if not match:
                raise ValueError('Unrecognized APT installation plan')
            wanted.add(match.groups())
    if not wanted:
        raise ValueError('Empty package plan; the offline resolver must use an empty status database')
    found = {}
    for path in sorted((state/'archives').glob('*.deb')):
        metadata = subprocess.check_output(['dpkg-deb','-f',str(path),'Package','Version','Architecture'],text=True)
        package, version, package_architecture = [line.split(': ',1)[-1] for line in metadata.splitlines()]
        if (package,version) in wanted:
            if package_architecture not in (architecture,'all'):
                raise ValueError('Package architecture mismatch')
            found[(package,version)] = path
    if wanted != found.keys():
        raise ValueError('Missing selected package archives; fetch the package group first')
    return sorted(found.values())

