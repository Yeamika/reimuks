"""Resolve selected board overlays and validate their layer manifests."""
import json
from pathlib import Path
import re

REPO = Path(__file__).resolve().parents[1]


def profile_name(profile):
    name = profile.removeprefix('desktop/')
    if name not in ('server', 'kde', 'gnome'):
        raise ValueError('Unsupported board profile: '+profile)
    return name


def profile_configuration(board, profile):
    name = profile_name(profile)
    config_path = REPO/'config/boards'/board/(name+'.json')
    config = json.loads(config_path.read_text())
    if config.get('schema') != 1 or config.get('board') != board:
        raise ValueError('Board profile configuration identity mismatch')
    if config.get('profile') != 'desktop/'+name:
        raise ValueError('Board profile configuration profile mismatch')
    return config


def layer_root(board, reference):
    path = Path(reference)
    if path.is_absolute() or '..' in path.parts or not path.parts:
        raise ValueError('Invalid overlay reference: '+reference)
    if path.parts[0] == 'services':
        if len(path.parts) != 2:
            raise ValueError('Invalid shared service overlay: '+reference)
        base = REPO/'overlays'
    else:
        if len(path.parts) != 1:
            raise ValueError('Invalid board overlay: '+reference)
        base = REPO/'devices'/board/'overlays'
    root = (base/path).resolve()
    if not root.is_relative_to(base.resolve()):
        raise ValueError('Overlay path escapes its source root: '+reference)
    return root


def load_layer(board, reference):
    root = layer_root(board, reference)
    path = root/'layer.json'
    descriptor = json.loads(path.read_text())
    if descriptor.get('schema') != 1 or descriptor.get('id') != Path(reference).name:
        raise ValueError('Overlay descriptor identity mismatch: '+reference)
    return root, descriptor


def selected_layers(board, profile):
    config = profile_configuration(board, profile)
    references = config.get('overlays')
    if not isinstance(references, list) or len(references) != len(set(references)):
        raise ValueError('Board profile overlays must be a unique list')
    selected = [(reference, *load_layer(board, reference)) for reference in references]
    return config, selected


def catalog(board):
    profiles = {}
    selected_by = {}
    profile_dir = REPO/'config/boards'/board
    for path in sorted(profile_dir.glob('*.json')):
        if path.name == 'packages.json':
            continue
        profile = path.stem
        config, selected = selected_layers(board, profile)
        profiles[profile] = {
            'profile': config['profile'],
            'kernel': config.get('kernel'),
            'overlays': [item[0] for item in selected],
            'builder': config.get('builder')
        }
        kernel = config.get('kernel')
        if kernel:
            selected_by.setdefault(kernel, []).append(profile)
        for reference, _, descriptor in selected:
            selected_by.setdefault(reference, []).append(profile)
    available = []
    for path in sorted((REPO/'devices'/board/'overlays').glob('*/layer.json')):
        reference = path.parent.name
        _, descriptor = load_layer(board, reference)
        available.append((reference, descriptor))
    for path in sorted((REPO/'overlays/services').glob('*/layer.json')):
        reference = 'services/'+path.parent.name
        _, descriptor = load_layer(board, reference)
        if reference not in {name for name, _ in available}:
            available.append((reference, descriptor))
    return {
        'board': board,
        'profiles': profiles,
        'layers': [{
            'id': descriptor['id'],
            'reference': reference,
            'kind': descriptor.get('kind'),
            'builder': descriptor.get('build'),
            'selected_by': selected_by.get(reference, [])
        } for reference, descriptor in available]
    }
