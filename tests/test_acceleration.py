"""Desktop API policy does not replace hardware drivers or disable isolation."""
from pathlib import Path
import runpy
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import acceleration
import distributions


class AccelerationTest(unittest.TestCase):
    def test_desktop_override_preserves_packaged_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            entry = root/'usr/share/applications/google-chrome.desktop'
            entry.parent.mkdir(parents=True)
            content = '[Desktop Entry]\nExec=/usr/bin/google-chrome-stable %U\n'
            entry.write_text(content)
            mode = root.stat().st_mode & 0o7777
            acceleration.install(root, 'kde', distributions.load_distribution())
            self.assertEqual(root.stat().st_mode & 0o7777, mode)
            self.assertEqual(entry.read_text(), content)
            self.assertIn('/usr/bin/reimuks-chrome %U', (root/'etc/skel/.local/share/applications/google-chrome.desktop').read_text())
            self.assertTrue((root/'usr/bin/reimuks-chrome').stat().st_mode & 0o111)

    def test_server_has_no_browser_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            acceleration.install(root, 'server', distributions.load_distribution())
            self.assertFalse(list(root.iterdir()))

    def test_vulkan_is_optional_and_sandbox_stays_enabled(self):
        script = Path(__file__).resolve().parents[1]/'overlays/apps/remote/files/usr/bin/reimuks-chrome'
        for extra, angle in [([], 'gles'), (['--reimuks-vulkan'], 'vulkan')]:
            with patch.object(sys, 'argv', [str(script), *extra, 'about:blank']), patch('os.execve') as execute, patch.object(Path, 'exists', return_value=False):
                runpy.run_path(str(script), run_name='__main__')
                argv = execute.call_args.args[1]
                self.assertIn('--use-angle='+angle, argv)
                self.assertNotIn('--no-sandbox', argv)
                self.assertNotIn('--disable-gpu-sandbox', argv)

    def test_vulkan_uses_board_supplied_environment_only_when_requested(self):
        script = Path(__file__).resolve().parents[1]/'overlays/apps/remote/files/usr/bin/reimuks-chrome'
        policy = json.dumps({'vulkan_environment': {'VK_DRIVER_FILES': '/usr/share/example/icd.json'}})
        for extra, enabled in [([], False), (['--reimuks-vulkan'], True)]:
            with patch.object(sys, 'argv', [str(script), *extra]), patch('os.execve') as execute, patch.object(Path, 'exists', return_value=True), patch.object(Path, 'read_text', return_value=policy), patch.dict('os.environ', {}, clear=True):
                runpy.run_path(str(script), run_name='__main__')
                environment = execute.call_args.args[2]
                self.assertEqual('VK_DRIVER_FILES' in environment, enabled)
