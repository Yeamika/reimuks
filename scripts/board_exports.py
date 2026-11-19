"""Consume a board's public userspace exports without knowing driver layout."""
import json
from pathlib import Path


def relative_path(root, value):
    path = Path(value)
    root = root.resolve()
    result = (root / path).resolve()
    if path.is_absolute() or not result.is_relative_to(root):
        raise ValueError(f'Invalid board export path: {value}')
    return result


def output_path(root, value, declared):
    """Allow an explicitly declared output link, retaining containment below it."""
    path, prefix = Path(value), Path(declared)
    if (path.is_absolute() or prefix.is_absolute() or '..' in path.parts or
            '..' in prefix.parts or not prefix.parts):
        raise ValueError(f'Invalid board output path: {value}')
    try:
        relative = path.relative_to(prefix)
    except ValueError:
        raise ValueError(f'Artifact outside declared board output: {value}') from None
    return relative_path((root/prefix).resolve(), relative)


def manifest(board):
    config = json.loads((board / 'board.json').read_text())
    reference = config.get('userspace_manifest')
    if not reference:
        raise ValueError('Board has no userspace export manifest')
    # The descriptor may point into a checked-out dependency (including a local
    # symlink); paths *inside* its export manifest stay in that dependency.
    relative = Path(reference)
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('Invalid userspace manifest reference')
    path = (board / relative).resolve()
    data = json.loads(path.read_text())
    if data.get('schema') != 1 or data.get('board') != config.get('board'):
        raise ValueError('Board userspace export identity mismatch')
    return path.parent, data


def component(board, name):
    root, data = manifest(board)
    try:
        entry = data['components'][name]
    except KeyError:
        raise ValueError(f'Board does not export userspace component: {name}') from None
    return relative_path(root, entry['userspace'])


def exported_file(board, name):
    _, data = manifest(board)
    try:
        entry = data['exports'][name]
    except KeyError:
        raise ValueError(f'Unknown board userspace export: {name}') from None
    return relative_path(component(board, entry['component']), entry['file'])


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--board', type=Path, required=True)
    parser.add_argument('--export', required=True)
    args = parser.parse_args()
    print(exported_file(args.board.resolve(), args.export))


if __name__ == '__main__':
    main()
