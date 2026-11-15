"""A Korean translation suffix must not be mistaken for a kernel module."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from verify import is_module_object


class ModuleArchive(unittest.TestCase):
    def test_korean_text_is_not_a_module(self):
        self.assertFalse(is_module_object('빔 길잡이\n'.encode()))

    def test_relocatable_elf_is_a_module(self):
        header=bytearray(20);header[:6]=b'\x7fELF\x02\x01';header[16:18]=(1).to_bytes(2,'little')
        self.assertTrue(is_module_object(header))
        header[16:18]=(3).to_bytes(2,'little')
        self.assertFalse(is_module_object(header))
