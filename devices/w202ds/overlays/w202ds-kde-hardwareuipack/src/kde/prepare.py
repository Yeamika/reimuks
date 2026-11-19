#!/usr/bin/env python3
"""Prepare user-level board applets without changing distro-owned packages."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile

SOURCE = Path(__file__).resolve().parent


def replace(path, before, after):
    original = path.read_text()
    if original.count(before) != 1:
        raise ValueError('Unsupported Plasma structure: '+str(path))
    path.write_text(original.replace(before, after, 1))


def prepare(root):
    root = root.resolve()
    if root == Path('/') or not (root/'var/lib/dpkg/status').is_file():
        raise ValueError('Expected an offline configured distro rootfs')
    # User-level template override: keep the distro's complete standard panel
    # and change only its initial edge. Saved user layouts remain independent.
    panel_source = root/'usr/share/plasma/layout-templates/org.kde.plasma.desktop.defaultPanel'
    panel_target = root/'etc/skel/.local/share/plasma/layout-templates/org.kde.plasma.desktop.defaultPanel'
    if not panel_source.is_dir():
        raise ValueError('Missing standard Plasma panel layout template')
    shutil.copytree(panel_source, panel_target, dirs_exist_ok=True)
    panel_script = panel_target/'contents/layout.js'
    text = panel_script.read_text()
    if text.count('var panel = new Panel') != 1:
        raise ValueError('Unsupported standard Plasma panel layout')
    panel_script.write_text(text.replace('var panel = new Panel',
                                        'var panel = new Panel\npanel.location = "left"'))
    shared = root/'usr/share/plasma/plasmoids'
    target = root/'etc/skel/.local/share/plasma/plasmoids'
    target.mkdir(parents=True, exist_ok=True)
    marker = root/'usr/share/reimuks/w202ds-kde-integration.json'
    sources = {str(p.relative_to(SOURCE)): hashlib.sha256(p.read_bytes()).hexdigest()
               for directory in ('plasma-hardware', 'plasma-hotspot')
               for p in sorted((SOURCE/directory).glob('*'))
               if p.suffix in ('.py', '.qml')}
    if marker.exists():
        previous = json.loads(marker.read_text())
        if previous.get('schema') != 2 or previous.get('installation') != 'user-skeleton':
            raise ValueError('Old system-level integration detected; rebuild from clean distro packages')
        if previous['sources'] != sources:
            raise ValueError('Applet integration sources changed; rebuild from clean distro packages')
        for name, expected in previous['files'].items():
            if hashlib.sha256((target/name).read_bytes()).hexdigest() != expected:
                raise ValueError('Installed applet was modified: '+name)
        return
    names = ['org.kde.plasma.private.systemtray', 'org.kde.plasma.battery',
             'org.kde.plasma.networkmanagement']
    with tempfile.TemporaryDirectory(dir=target, prefix='.board-kde-') as temporary:
        staging = Path(temporary)
        for name in names:
            shutil.copytree(shared/name, staging/name, symlinks=True)
        tray = staging/names[0]/'contents/ui'
        replace(tray/'main.qml', 'import QtQuick\n',
                'import QtQuick\nimport org.reimuks.popupcache 1.0\n')
        replace(tray/'ExpandedRepresentation.qml', '        // Grid view of all available items\n',
                '''        UsbItem {
            Layout.fillWidth: true
            visible: !systemTrayState.activeApplet
        }
        HardwareControls {
            Layout.fillWidth: true
            visible: !systemTrayState.activeApplet
        }

        // Grid view of all available items
''')
        battery = staging/names[1]/'contents/ui'
        replace(battery/'PopupDialog.qml', '                PowerProfileItem {\n',
                '''                ChargingItem { width: parent.width }
                PowerProfileItem {
''')
        replace(battery/'main.qml', 'batteryPluggedIn: batteryControl.pluggedIn',
                'batteryPluggedIn: batteryControl.state === BatteryControlModel.Charging')
        replace(battery/'BatteryItem.qml', 'pluggedIn: root.pluggedIn && root.batteryIsPowerSupply',
                'pluggedIn: root.batteryChargeState === BatteryControlModel.Charging && root.batteryIsPowerSupply')
        for ui in (tray, battery):
            for filename in ('HardwareControls.qml', 'ChargingItem.qml', 'UsbItem.qml'):
                shutil.copy2(SOURCE/'plasma-hardware'/filename, ui/filename)
        patcher = SOURCE/'plasma-hotspot/patch_applet.py'
        spec = importlib.util.spec_from_file_location('board_hotspot_patch', patcher)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        network = staging/names[2]
        module.patch(network)
        shutil.copy2(SOURCE/'plasma-hotspot/HotspotSwitcher.qml', network/'contents/ui/HotspotSwitcher.qml')
        # Publish complete user packages; never modify APT-owned originals.
        for name in names:
            if (target/name).exists():
                raise ValueError('An unrelated skeleton applet override exists: '+name)
        for name in names:
            shutil.move(staging/name, target/name)
    files = {str(p.relative_to(target)): hashlib.sha256(p.read_bytes()).hexdigest()
             for name in names for p in sorted((target/name).rglob('*')) if p.is_file()}
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({'schema': 2, 'installation': 'user-skeleton',
                                'sources': sources, 'files': files}, indent=2)+'\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rootfs', type=Path, required=True)
    args = parser.parse_args()
    prepare(args.rootfs)
