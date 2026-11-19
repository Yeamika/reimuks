"""Resolve build storage per invocation or board without binding shared sources."""
import argparse
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def selected_board(board=None):
    name = board or os.environ.get('REIMUKS_BOARD', 'w202ds')
    if not name.isidentifier():
        raise ValueError('Invalid board: ' + name)
    return name


def shared_root(*, repo=None):
    repo = Path(repo) if repo is not None else REPO
    return Path(os.environ.get('REIMUKS_SHARED_BUILD_ROOT', repo/'build')).expanduser().resolve()


def build_root(board=None, *, repo=None):
    repo = Path(repo) if repo is not None else REPO
    name = selected_board(board)
    override = os.environ.get('REIMUKS_BUILD_ROOT') or os.environ.get('REIMUKS_LEGACY_BUILD_ROOT')
    if override:
        return Path(override).expanduser().resolve()
    return (shared_root(repo=repo)/'boards'/name).resolve()


def board_root(board=None, *, repo=None):
    return build_root(board, repo=repo)


def boot_paths(board=None, *, repo=None):
    name = selected_board(board)
    repo = Path(repo) if repo is not None else REPO
    override = os.environ.get('REIMUKS_BOOT_ROOT')
    local = repo/'devices'/name/'boot/output'
    if not override and local.is_symlink():
        override = str(local.resolve())
    if override:
        root = Path(override).expanduser().resolve()
        return root/'work', root/'artifacts', root/'source-cache'
    root = build_root(name, repo=repo)
    return root/'boot/work', root/'artifacts/boot', root/'boot-sources'


def temporary_environment(root, env=None):
    """Keep subprocess scratch/cache under the selected output tree."""
    env = dict(os.environ if env is None else env)
    root = Path(root).resolve()
    for key, relative in [('TMPDIR', 'tmp'), ('XDG_CACHE_HOME', 'cache')]:
        path = root/relative
        path.mkdir(parents=True, exist_ok=True)
        env[key] = str(path)
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    return env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--board')
    parser.add_argument('--kind', choices=['build', 'board', 'boot', 'shared'], default='board')
    args = parser.parse_args()
    if args.kind == 'boot':
        result = boot_paths(args.board)[1]
    elif args.kind == 'shared':
        result = shared_root()
    else:
        result = (build_root if args.kind == 'build' else board_root)(args.board)
    print(result)


if __name__ == '__main__':
    main()
