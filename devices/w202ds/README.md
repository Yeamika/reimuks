# W202DS Board

W202DS board integration lives in this directory. Kernel and boot sources are linked
from their owning projects; this repository selects hardware components and defines
board and profile policy.

```text
devices/w202ds/
├── board.json
├── kernel -> ...
├── boot -> ...
├── initramfs/rootfs/
├── overlays/
│   ├── w202ds-kernel/
│   ├── w202ds-hardwarepack2/
│   ├── w202ds-server/
│   ├── w202ds-hall-overlay/
│   ├── w202ds-kde-hardwareuipack/
│   └── w202ds-gnome-hardwareuipack/
└── tests/
```

Each board overlay has a `layer.json`. The hardware pack owns common board files,
userspace source and producer checks. Server selects the hardware pack, shared power
key policy, server login policy and Hall display policy. KDE and GNOME select the
same hardware pack and their own interface pack. Profile selections are in
`config/boards/w202ds/{server,kde,gnome}.json`; the kernel layer only declares the
matching kernel and module source artifacts.

The generic power key policy is in `overlays/services/powerkey/`. Early boot files
remain separate under `initramfs/rootfs/`. No rootfs/profile copy is maintained in
parallel with the overlays.

Inspect the selections:

```sh
python3 scripts/overlay-scan.py --board w202ds
```

The normal REIMUKS entrypoint builds the selected board integration and rootfs:

```sh
python3 reimuks.py --board w202ds --target userspace rootfs --profile desktop/server
```

Local compiler, producer and SDK paths belong in
`devices/w202ds/overlays/w202ds-hardwarepack2/build.local.json`; use the adjacent
`build.example.json` as a template. That local file is not part of the source layer.
