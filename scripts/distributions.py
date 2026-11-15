"""Distribution registry, package mapping and rootfs identity checks."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

REPO = Path(__file__).resolve().parents[1]
DEFAULT = 'debian/trixie'


def distributions(repo=REPO):
    return {p.relative_to(repo/'distributions').with_suffix('').as_posix(): p
            for p in sorted((repo/'distributions').glob('*/*.json'))}


def load_distribution(name=DEFAULT, repo=REPO):
    registry = distributions(repo)
    if name not in registry:
        raise ValueError(f'Unknown distribution: {name}')
    data = json.loads(registry[name].read_text())
    if data.get('schema') != 1 or data.get('id') != name:
        raise ValueError(f'Invalid distribution description: {name}')
    if data.get('backend') != 'apt-dpkg' or data.get('os_release', {}).get('ID') != 'debian':
        raise ValueError('Only the Debian apt-dpkg backend is implemented')
    if data.get('architecture') != 'arm64':
        raise ValueError('Only arm64 userspace/initramfs is implemented')
    for token in [data.get('suite', ''), *data.get('components', [])]:
        if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9+./_-]*', token):
            raise ValueError('Invalid suite/component in distribution')
    for key in ('build_repositories', 'target_repositories'):
        if not data.get(key) or not data.get('components'):
            raise ValueError(f'Missing {key} or components')
        for source in data[key]:
            if (not re.fullmatch(r'https?://[^\s"\[\]]+', source['uri']) or
                    not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9+._-]*', source['suite'])):
                raise ValueError('Invalid repository URI or suite')
    # Expand references before computing identity: a layout-only split must not
    # invalidate caches, while edits to any referenced package list must do so.
    for profile, mapping in data.get('profiles', {}).items():
        if isinstance(mapping, str):
            relative = Path(mapping)
            base = registry[name].parent.resolve()
            path = (base / relative).resolve()
            if relative.is_absolute() or '..' in relative.parts or not path.is_relative_to(base) or path.suffix != '.json':
                raise ValueError(f'Invalid profile mapping path: {mapping}')
            if not path.is_file():
                raise ValueError(f'Missing profile mapping: {mapping}')
            mapping = json.loads(path.read_text())
        if not isinstance(mapping, dict):
            raise ValueError(f'Invalid profile mapping: {profile}')
        if 'install_recommends' in mapping and type(mapping['install_recommends']) is not bool:
            raise ValueError(f'Invalid install_recommends in profile mapping: {profile}')
        for key in ('packages', 'required_packages'):
            values = mapping.get(key, [])
            if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
                raise ValueError(f'Invalid {key} in profile mapping: {profile}')
        data['profiles'][profile] = mapping
    extra = data.get('additional_packages')
    if isinstance(extra, str):
        path = Path(extra)
        base = registry[name].parent.resolve()
        if path.is_absolute() or '..' in path.parts or not (base/path).resolve().is_relative_to(base):
            raise ValueError('Invalid additional package mapping')
        extra = json.loads((base/path).read_text())
        data['additional_packages'] = extra
    if extra is not None:
        if not isinstance(extra, dict):
            raise ValueError('Invalid additional packages')
        for key in ('profiles', 'packages', 'acceleration_packages'):
            if not isinstance(extra.get(key, []), list) or not all(isinstance(v, str) for v in extra.get(key, [])):
                raise ValueError('Invalid additional package list')
        for source in extra.get('repositories', []):
            key = Path(source['keyring'])
            base = registry[name].parent.resolve()
            if key.is_absolute() or '..' in key.parts or not (base/key).resolve().is_relative_to(base):
                raise ValueError('Invalid additional repository key path')
            if hashlib.sha256((base/key).read_bytes()).hexdigest() != source['keyring_sha256']:
                raise ValueError('Additional repository key digest mismatch')
            if (not re.fullmatch(r'https://[^\s"\[\]]+', source['uri']) or
                    not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9+._-]*', source['suite']) or
                    not re.fullmatch(r'/usr/share/keyrings/[a-zA-Z0-9._-]+\.asc', source['target_keyring'])):
                raise ValueError('Invalid additional repository')
    return data


def identity(distribution):
    digest = hashlib.sha256(json.dumps(distribution, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {key: distribution[key] for key in ('id', 'backend', 'suite', 'architecture')} | {'config_sha256': digest}


def profile_name(name):
    return 'desktop/'+name if name in ('server', 'kde', 'gnome') else name


def resolve_profile(name, distribution, repo=REPO, seen=()):
    name = profile_name(name)
    if name in seen:
        raise ValueError('Profile inheritance cycle: '+name)
    if not re.fullmatch(r'[a-z0-9_-]+(?:/[a-z0-9_-]+)*', name):
        raise ValueError('Invalid profile: '+name)
    path = repo/'profiles'/(name+'.json')
    if not path.is_file():
        raise ValueError('Unknown profile: '+name)
    definition = json.loads(path.read_text())
    if definition.get('status') == 'placeholder':
        raise ValueError('Profile is a placeholder: '+name)
    mapping = distribution.get('profiles', {}).get(name)
    if mapping is None:
        raise ValueError(f'{distribution["id"]} does not implement profile {name}')
    parent = (resolve_profile(definition['extends'], distribution, repo, (*seen, name))
              if 'extends' in definition else {})
    result = parent | definition | mapping
    result.setdefault('install_recommends', distribution.get('install_recommends', False))
    for key in ('packages', 'required_packages'):
        result[key] = list(dict.fromkeys(parent.get(key, [])+mapping.get(key, [])))
    extra = distribution.get('additional_packages', {})
    if name in extra.get('profiles', []):
        # Applications are an optional offline bundle; API libraries belong to the desktop.
        additions = extra.get('acceleration_packages', [])
        for key in ('packages', 'required_packages'):
            result[key] = list(dict.fromkeys(result[key] + additions))
    return result


def additional_repositories(distribution, profile, include_apps=False):
    extra = distribution.get('additional_packages', {})
    return extra.get('repositories', []) if include_apps and profile and profile_name(profile) in extra.get('profiles', []) else []


def repository_key(distribution, source, repo=REPO):
    return repo/'distributions'/Path(distribution['id']).parent/source['keyring']


def sources_list(distribution, target=False, keyring=None, profile=None, include_apps=False):
    options = f' [signed-by={keyring}]' if keyring else ''
    components = ' '.join(distribution['components'])
    text = ''.join(f'deb{options} {source["uri"]} {source["suite"]} {components}\n'
                   for source in distribution['target_repositories' if target else 'build_repositories'])
    for source in additional_repositories(distribution, profile, include_apps):
        key = source['target_keyring'] if target else repository_key(distribution, source)
        text += (f'deb [arch={distribution["architecture"]} signed-by={key}] '
                 f'{source["uri"]} {source["suite"]} {" ".join(source["components"])}\n')
    return text


def check_os_release(text, distribution):
    values = dict(line.split('=', 1) for line in text.splitlines() if '=' in line and not line.startswith('#'))
    for key, expected in distribution['os_release'].items():
        if values.get(key, '').strip('\"\'') != expected:
            raise ValueError(f'Rootfs distribution mismatch: expected {key}={expected}')


def check_package_versions(specification, versions):
    """Enforce upstream version floors, independently of Debian packaging epochs."""
    for package, minimum in specification.get('minimum_package_versions', {}).items():
        actual = versions.get(package)
        if actual is None or subprocess.run(
                ['dpkg', '--compare-versions', actual.split(':', 1)[-1], 'ge', minimum],
                check=False).returncode != 0:
            raise ValueError(f'{package} requires >= {minimum}; available/installed: {actual or "missing"}')
