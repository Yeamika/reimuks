"""Execute target userspace checks before publishing a rootfs archive.

This smoke test does not simulate hardware or a PID 1 boot.
"""
import re
import struct


def verify(root, profile, runner):
    references = set()
    for script in sorted((root / 'usr/libexec').glob('*')):
        if not script.is_file() or script.read_bytes()[:2] != b'#!':
            continue
        # Include conditional helper invocations missed by --help smoke tests.
        references.update(re.findall(r'/usr/libexec/[A-Za-z0-9_.+-]+',
                                    script.read_text(errors='replace')))
    commands = [
        ['/bin/sh', '-ec', 'test -x /sbin/init; test -x /usr/bin/login'],
        ['/usr/bin/login', '--help'],
        ['/usr/bin/systemctl', '--version'],
        ['/bin/sh', '-ec', '. /etc/default/locale; export LANG; '
         '/usr/bin/python3 -c \'import locale; locale.setlocale(locale.LC_ALL, "")\''],
    ]
    scripts = {'/bin/sh': [], '/bin/bash': []}
    for script in sorted((root / 'usr/libexec').glob('*')):
        if script.is_file():
            interpreter = script.read_bytes().split(b'\n', 1)[0].decode(errors='replace')[2:]
            if interpreter in scripts:
                scripts[interpreter].append('/'+str(script.relative_to(root)))
    for interpreter, files in scripts.items():
        if files:
            commands.append([interpreter, '-ec',
                             'for file do '+interpreter+' -n "$file"; done',
                             'preflight', *files])
    for reference in sorted(references):
        commands.append(['/bin/sh', '-ec', 'test -x "$1"', 'preflight', reference])
    for binary in sorted((root / 'usr/libexec').glob('*')):
        if not binary.is_file():
            continue
        data = binary.read_bytes()
        if not data.startswith(b'\x7fELF'):
            continue
        if len(data) < 64 or data[4:6] != b'\x02\x01' or struct.unpack_from('<H', data, 18)[0] != 183:
            raise ValueError('Expected ARM64 helper: '+binary.name)
        offset = struct.unpack_from('<Q', data, 32)[0]
        size, count = struct.unpack_from('<HH', data, 54)
        if size < 56 or offset + size * count > len(data):
            raise ValueError('Invalid ELF program headers: '+binary.name)
        for index in range(count):
            header = offset + index * size
            if struct.unpack_from('<I', data, header)[0] == 3:  # PT_INTERP
                start = struct.unpack_from('<Q', data, header + 8)[0]
                length = struct.unpack_from('<Q', data, header + 32)[0]
                interpreter = data[start:start + length].rstrip(b'\0').decode()
                if not interpreter.startswith('/') or '\0' in interpreter:
                    raise ValueError('Invalid ELF interpreter: '+binary.name)
                # Resolve all shared libraries without executing the hardware helper.
                commands.append([interpreter, '--list', '/'+str(binary.relative_to(root))])
    # Check newly supplied application/API consumers without starting a GPU,
    # browser sandbox or hardware service in the offline environment.
    applications = [root/'opt/google/chrome/chrome', root/'usr/share/code/code']
    applications += list((root/'usr/lib').glob('*/dri/v4l2_request_drv_video.so'))
    for binary in applications:
        if binary.is_file():
            commands.append(['/lib/ld-linux-aarch64.so.1', '--list', '/'+str(binary.relative_to(root))])
    if (root/'usr/bin/reimuks-chrome').is_file():
        commands.append(['/usr/bin/python3', '-c',
                         'import ast; ast.parse(open("/usr/bin/reimuks-chrome").read())'])
    if profile.removeprefix('desktop/') == 'kde':
        commands += [['/usr/bin/sddm', '--example-config'],
                     ['/usr/bin/env', 'QT_QPA_PLATFORM=offscreen',
                      '/usr/bin/kwin_wayland', '--version'],
                     ['/bin/sh', '-ec',
                      'set -- /usr/lib/*/qt5/plugins/platforms/libqwayland-generic.so; '
                      'test -f "$1"; /lib/ld-linux-aarch64.so.1 --list "$1"'],
                     ['/bin/sh', '-ec', 'test -n "$(/usr/bin/fc-list :lang=zh family)"']]
    units = sorted({p.name for base in ('usr/lib/systemd/system', 'etc/systemd/system')
                    for p in (root / base).glob('w202*.service') if p.is_file()})
    if profile.removeprefix('desktop/') == 'kde':
        units.append('sddm.service')
    if units:
        commands.append(['/usr/bin/systemd-analyze', 'verify', '--man=no', *units])
    for command in commands:
        runner(root, command, timeout=120)
    return {'schema': 1, 'method': 'target-userspace', 'commands': commands,
            'hardware_tested': False}


if __name__ == '__main__':
    import argparse
    import json
    from pathlib import Path
    from build import proot

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rootfs', type=Path, required=True)
    parser.add_argument('--profile', choices=['server', 'kde', 'gnome'], required=True)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    report = verify(args.rootfs.resolve(), args.profile, proot)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2)+'\n')
