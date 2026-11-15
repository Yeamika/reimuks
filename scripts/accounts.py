"""Desktop rootfs account policy; secret values travel through stdin only."""
import json
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LOCAL_CONFIG = REPO / 'config/accounts.local.json'
DEFAULT_CONFIG = REPO / 'config/accounts.json'
USERS = ('root', 'reimuks')


def load_accounts(path=None, environ=None):
    env = os.environ if environ is None else environ
    path = Path(path) if path is not None else LOCAL_CONFIG if LOCAL_CONFIG.exists() else DEFAULT_CONFIG
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        raise ValueError('Cannot read desktop account configuration') from None
    if not isinstance(data, dict) or set(data) != {'schema', 'desktop'} or type(data['schema']) is not int or data['schema'] != 1:
        raise ValueError('Unsupported desktop account configuration schema')
    users = data['desktop']
    if not isinstance(users, dict) or set(users) != set(USERS):
        raise ValueError('Desktop accounts must specify root and reimuks')
    result = {}
    for name in USERS:
        entry = users[name]
        if not isinstance(entry, dict) or len(entry) != 1:
            raise ValueError(f'{name}: choose exactly one account password policy')
        kind, value = next(iter(entry.items()))
        if kind == 'locked':
            if value is not True:
                raise ValueError(f'{name}: locked must be true')
        elif kind in ('password', 'password_hash', 'password_env'):
            if kind == 'password_env':
                if not isinstance(value, str) or not value or value not in env:
                    raise ValueError(f'{name}: password environment variable is unavailable')
                value = env[value]
                kind = 'password'
            if not isinstance(value, str) or not value or any(c in value for c in '\r\n\0'):
                raise ValueError(f'{name}: password must be nonempty and contain no line breaks or NUL')
            if kind == 'password_hash' and (not value.startswith('$') or ':' in value):
                raise ValueError(f'{name}: expected a modular crypt password hash')
        else:
            raise ValueError(f'{name}: unsupported account password policy')
        result[name] = (kind, value)
    return result


def password_operations(policy):
    """Return command/stdin pairs without placing credentials in arguments."""
    commands = []
    for name, (kind, value) in policy.items():
        if kind == 'locked':
            commands.append((['/usr/bin/passwd', '-l', name], None))
        else:
            command = ['/usr/sbin/chpasswd'] + (['-e'] if kind == 'password_hash' else [])
            commands.append((command, f'{name}:{value}\n'))
    return commands
