#!/usr/bin/python3
"""Install a user-local Plasma NM override and its unprivileged NM helper."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from patch_applet import patch

SOURCE = Path(__file__).resolve().parent
sys.path.insert(0, str(SOURCE.parents[6]/'scripts'))
from output_paths import board_root
NATIVE = board_root('w202ds')/'device-controls/rootfs/usr/libexec'
BASE = Path("/usr/share/plasma/plasmoids/org.kde.plasma.networkmanagement")
TARGET = Path.home()/".local/share/plasma/plasmoids/org.kde.plasma.networkmanagement"
RECORDS = Path(os.environ.get("XDG_STATE_HOME",str(Path.home()/".local/state")))/"w202ds/plasma-hotspot"
HELPER = Path("/usr/libexec/w202-hotspot-switch")
DISPATCHER = Path("/etc/NetworkManager/dispatcher.d/90-w202-hotspot-scan")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    for name in ('w202-hotspot-switch', 'w202-hotspot-scan'):
        header = (NATIVE/name).read_bytes()[:20]
        if len(header) != 20 or header[:6] != b'\x7fELF\x02\x01' or header[18:20] != b'\xb7\x00':
            raise RuntimeError('Build the target C helpers first')
    version = subprocess.check_output(
        ["dpkg-query","-W","-f","$"+"{Version}","plasma-nm"],text=True).strip()
    supplicant_version = subprocess.check_output(
        ["dpkg-query","-W","-f","$"+"{Version}","wpasupplicant"],text=True).strip()
    if TARGET.exists() and not (TARGET/"w202-hotspot-fix.json").is_file():
        raise RuntimeError("A different user applet override already exists")
    previous = {}
    record = RECORDS/"installed.json"
    if record.is_file():
        previous = json.loads(record.read_text())
    for installed, name, key, legacy in (
        (HELPER, "w202-hotspot-switch", "helper_sha256", b"Prepare and restore the Wi-Fi device around Plasma NM"),
        (DISPATCHER, "w202-hotspot-scan", "dispatcher_sha256", b"W202DS hotspot scan drain"),
    ):
        if installed.exists() and digest(installed) not in (digest(NATIVE/name), previous.get(key)) and legacy not in installed.read_bytes():
            raise RuntimeError("An unrelated or modified Wi-Fi helper already exists")
    RECORDS.mkdir(parents=True,exist_ok=True)
    TARGET.parent.mkdir(parents=True,exist_ok=True)
    temp = TARGET.with_name(".w202-networkmanagement-"+str(os.getpid()))
    shutil.copytree(BASE,temp)
    patch(temp)
    shutil.copy2(SOURCE/"HotspotSwitcher.qml",temp/"contents/ui/HotspotSwitcher.qml")
    manifest = {"package_version":version,"supplicant_version":supplicant_version,"installed_at":int(time.time()),
                "source_sha256":{name:digest(BASE/"contents/ui"/name)
                    for name in ["main.qml","Toolbar.qml","PopupDialog.qml"]},
                "helper_sha256":digest(NATIVE/"w202-hotspot-switch"),
                "dispatcher_sha256":digest(NATIVE/"w202-hotspot-scan")}
    (temp/"w202-hotspot-fix.json").write_text(json.dumps(manifest,indent=2)+"\n")
    if HELPER.exists():
        shutil.copy2(HELPER,RECORDS/("helper-before-"+str(time.time_ns())))
    if DISPATCHER.exists():
        shutil.copy2(DISPATCHER,RECORDS/("dispatcher-before-"+str(time.time_ns())))
    subprocess.run(["sudo","-n","install","-D","-m","0755",
                    str(NATIVE/"w202-hotspot-scan"),str(DISPATCHER)],check=True)
    subprocess.run(["sudo","-n","install","-D","-m","0755",
                    str(NATIVE/"w202-hotspot-switch"),str(HELPER)],check=True)
    if TARGET.exists():
        TARGET.rename(RECORDS/("applet-before-"+str(time.time_ns())))
    temp.rename(TARGET)
    (RECORDS/"installed.json").write_text(json.dumps(manifest,indent=2)+"\n")
    print(json.dumps({"installed_applet":str(TARGET),"helper":str(HELPER),**manifest},indent=2))


if __name__=="__main__":
    main()
