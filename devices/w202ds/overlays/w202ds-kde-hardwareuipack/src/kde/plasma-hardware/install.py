#!/usr/bin/python3
"""Embed board controls in a private copy of Plasma's existing tray popup."""
from pathlib import Path
import json
import shutil
import time


def install(name, filename, anchor, addition):
    base = Path('/usr/share/plasma/plasmoids') / name
    target = Path.home() / '.local/share/plasma/plasmoids' / name
    records = Path.home() / '.local/state/w202ds/plasma-hardware'
    if target.exists() and not (target / 'w202-hardware.json').exists():
        raise RuntimeError('An unrelated system tray override already exists')
    text = (base / 'contents/ui' / filename).read_text()
    if text.count(anchor) != 1:
        raise RuntimeError('Unsupported tray structure; original left unchanged')
    text = text.replace(anchor, addition + anchor, 1)
    records.mkdir(parents=True, exist_ok=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name('.w202-install-' + name)
    if temp.exists():
        raise RuntimeError('Previous incomplete installation needs inspection')
    shutil.copytree(base, temp)
    (temp / 'contents/ui' / filename).write_text(text)
    shutil.copy2(Path(__file__).with_name('HardwareControls.qml'), temp / 'contents/ui')
    shutil.copy2(Path(__file__).with_name('ChargingItem.qml'), temp / 'contents/ui')
    shutil.copy2(Path(__file__).with_name('UsbItem.qml'), temp / 'contents/ui')
    if name == 'org.kde.plasma.battery':
        # Keep external-power state for policy/tooltips; only the charging
        # overlay follows the actual battery charge state.
        for filename, before, after in (
            ('main.qml', 'batteryPluggedIn: batteryControl.pluggedIn',
             'batteryPluggedIn: batteryControl.state === BatteryControlModel.Charging'),
            ('BatteryItem.qml', 'pluggedIn: root.pluggedIn && root.batteryIsPowerSupply',
             'pluggedIn: root.batteryChargeState === BatteryControlModel.Charging && root.batteryIsPowerSupply'),
        ):
            path = temp / 'contents/ui' / filename
            original = path.read_text()
            if original.count(before) != 1:
                raise RuntimeError('Unsupported battery icon binding; original left unchanged')
            path.write_text(original.replace(before, after, 1))
    (temp / 'w202-hardware.json').write_text(json.dumps({'integration': 'tray-home'}) + '\n')
    if target.exists():
        target.rename(records / (name + '-before-' + str(time.time_ns())))
    temp.rename(target)


def main():
    install('org.kde.plasma.private.systemtray', 'ExpandedRepresentation.qml',
            '        // Grid view of all available items\n', '''        UsbItem {
            Layout.fillWidth: true
            visible: !systemTrayState.activeApplet
        }

        HardwareControls {
            Layout.fillWidth: true
            visible: !systemTrayState.activeApplet
        }

''')
    install('org.kde.plasma.battery', 'PopupDialog.qml',
            '                PowerProfileItem {\n', '''                ChargingItem {
                    width: parent.width
                }

''')


if __name__ == '__main__':
    main()
