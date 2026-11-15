#!/usr/bin/env python3
"""Create and verify a FAT32 ESP image from an explicit file tree; never read GPT or flash."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from kernel import tool_environment


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def create(tree, output, size_mib, tools=None):
    tree, output = tree.resolve(), output.absolute()
    if not tree.is_dir() or output.is_relative_to(tree):
        raise ValueError('Use a source tree and a separate image output')
    if output.is_symlink() or (output.exists() and not output.is_file()):
        raise ValueError('Output must be a regular image file')
    output = output.resolve()
    if output.is_relative_to(tree):
        raise ValueError('Output resolves inside the source tree')
    if not 32 <= size_mib <= 2048*1024:
        raise ValueError('ESP size must be between 32 MiB and 2 TiB')
    env = tool_environment()
    if tools:
        env['PATH'] = str(tools.resolve())+os.pathsep+env['PATH']
    programs = {}
    for name in ('mkfs.fat', 'mcopy', 'mtype', 'fsck.fat'):
        programs[name] = shutil.which(name, path=env['PATH'])
        if not programs[name]:
            raise ValueError('Missing ESP tool: '+name+'; prepare dosfstools and mtools')
    files, names = {}, set()
    for path in sorted(tree.rglob('*')):
        relative = path.relative_to(tree)
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise ValueError('ESP trees cannot contain links or special files: '+str(relative))
        folded = relative.as_posix().casefold()
        if folded in names:
            raise ValueError('FAT path collision: '+str(relative))
        names.add(folded)
        for part in relative.parts:
            if part.endswith((' ', '.')) or any(ord(c)<32 or c in '<>:"\\|?*' for c in part):
                raise ValueError('Invalid FAT filename: '+str(relative))
        if path.is_file():
            if path.stat().st_size >= 2**32:
                raise ValueError('File exceeds FAT32 size limit: '+str(relative))
            files[relative.as_posix()] = {'bytes':path.stat().st_size,'sha256':digest(path)}
    if not files or not any(name.lower().endswith('.efi') for name in files):
        raise ValueError('ESP tree has no EFI application')
    if sum(entry['bytes'] for entry in files.values()) >= size_mib*1024**2:
        raise ValueError('ESP files do not fit within the requested image capacity')
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.'+output.name+'-', dir=output.parent)
    os.close(fd)
    image = Path(temporary)
    try:
        with image.open('wb') as stream:
            stream.truncate(size_mib*1024**2)
        subprocess.run([programs['mkfs.fat'],'-F','32','-S','512','-n','REIMUKSESP',str(image)], env=env, check=True)
        subprocess.run([programs['mcopy'],'-s','-i',str(image),
                        *[str(p) for p in sorted(tree.iterdir())], '::/'], env=env, check=True)
        subprocess.run([programs['fsck.fat'],'-n',str(image)], env=env, check=True)
        for name, expected in files.items():
            with subprocess.Popen([programs['mtype'],'-i',str(image),'::/'+name],
                                  env=env, stdout=subprocess.PIPE) as process:
                actual = hashlib.file_digest(process.stdout,'sha256').hexdigest()
                if process.wait() or actual != expected['sha256']:
                    raise ValueError('ESP readback mismatch: '+name)
        record = {'schema':1,'filesystem':'FAT32','bytes':image.stat().st_size,
                  'sha256':digest(image),'files':files}
        image.replace(output)
        output.with_suffix(output.suffix+'.json').write_text(json.dumps(record,indent=2)+'\n')
        return record
    finally:
        image.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tree',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--size-mib',type=int,required=True)
    parser.add_argument('--tools',type=Path,help='optional native dosfstools/mtools bin directory')
    args=parser.parse_args()
    try:
        record=create(args.tree,args.output,args.size_mib,args.tools)
    except (ValueError,OSError,subprocess.SubprocessError) as error:
        parser.exit(1,str(error)+'\n')
    print('ESP image verified:',record['bytes'],'bytes,',len(record['files']),'files')


if __name__=='__main__':
    main()
