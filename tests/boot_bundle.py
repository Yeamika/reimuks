import ctypes
import importlib.util
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('bundle', REPO/'scripts/boot_bundle.py')
bundle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bundle)


class BootBundleTest(unittest.TestCase):
    def test_actual_loader(self):
        image = (REPO/'build/kernel/Image').read_bytes()
        initrd = (REPO/'build/artifacts/initramfs-arm64.cpio.lz4').read_bytes()
        # Synthetic DT header only for packing tests, never a deployable board DTB.
        dtb = struct.pack('>10I', 0xd00dfeed, 40, *([0]*8))
        uuid = '01234567-89ab-cdef-0123-456789abcdef'
        boot, meta = bundle.assemble(image, initrd, dtb, uuid)
        with tempfile.TemporaryDirectory(dir=REPO/'build') as temp:
            out = Path(temp)/'parser.so'
            edk = REPO.parent/'edk2-ums9620/edk2/MdePkg/Include'
            source = REPO/'devices/w202ds/boot/pocketjs4edk2_uefi/efi/LinuxBoot/LinuxImage.c'
            wrapper = Path(temp)/'wrapper.c'
            wrapper.write_text('#include "'+str(source)+'"\n#pragma GCC visibility pop\n__attribute__((visibility("default"))) EFI_STATUS TestParse(CONST UINT8 *h, UINTN hb, CONST UINT8 *k, UINTN kb, UINT64 n, LINUX_IMAGE *o) { return LinuxParseImage(h,hb,k,kb,n,o); }\n')
            subprocess.run([str(REPO/'build/compiler/cc'), '-shared', '-fPIC',
                            '-fshort-wchar', '-I'+str(edk), '-I'+str(edk/'X64'),
                            str(wrapper), '-o', str(out)], check=True)
            class Layout(ctypes.Structure):
                _fields_ = [(n, ctypes.c_uint64) for n in ['kernel', 'offset', 'ramdisk', 'entry', 'memory']]
            parse = ctypes.CDLL(str(out)).TestParse
            parse.restype = ctypes.c_uint64
            parse.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p,
                              ctypes.c_size_t, ctypes.c_uint64, ctypes.POINTER(Layout)]
            layout = Layout()
            self.assertEqual(parse(boot[:4096],4096,image[:64],64,len(boot),ctypes.byref(layout)),0)
            self.assertEqual(boot[layout.offset:layout.offset+layout.ramdisk], initrd)
            self.assertNotEqual(parse(boot[:4096],4096,image[:64],64,len(boot)-1,ctypes.byref(layout)),0)
        self.assertEqual(len(meta),32)
        import zlib
        self.assertEqual(struct.unpack('<6I',meta[8:]),(len(image),len(initrd),len(dtb),zlib.crc32(image),zlib.crc32(initrd),zlib.crc32(dtb)))
        for bad in ['', uuid+'\n', uuid.replace('a','z'), uuid.replace('-','_')]:
            with self.assertRaises(ValueError): bundle.assemble(image,initrd,dtb,bad)


if __name__ == '__main__': unittest.main()
