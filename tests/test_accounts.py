import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import accounts
import build


class AccountsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'accounts.json'

    def write(self, root, user):
        self.path.write_text(json.dumps({'schema': 1, 'desktop': {'root': root, 'reimuks': user}}))

    def test_passwords_use_stdin_and_hashes_use_encrypted_mode(self):
        self.write({'password': 'root:secret'}, {'password_hash': '$6$salt$hash'})
        operations = accounts.password_operations(accounts.load_accounts(self.path))
        self.assertEqual(operations, [(['/usr/sbin/chpasswd'], 'root:root:secret\n'),
                                      (['/usr/sbin/chpasswd', '-e'], 'reimuks:$6$salt$hash\n')])
        self.assertNotIn('root:secret', repr([command for command, _ in operations]))

    def test_environment_and_locked_account(self):
        self.write({'locked': True}, {'password_env': 'PRIVATE_PASSWORD'})
        policy = accounts.load_accounts(self.path, {'PRIVATE_PASSWORD': 'test-value'})
        self.assertEqual(accounts.password_operations(policy),
                         [(['/usr/bin/passwd', '-l', 'root'], None),
                          (['/usr/sbin/chpasswd'], 'reimuks:test-value\n')])

    def test_rejects_injection_empty_and_ambiguous_policies_without_echoing_secret(self):
        for entry in ({'password': 'sensitive\nroot:injected'}, {'password': ''},
                      {'password': 'sensitive', 'locked': True}, {'password_hash': '!'},
                      {'locked': False}):
            with self.subTest(entry=entry):
                self.write(entry, {'locked': True})
                with self.assertRaises(ValueError) as error:
                    accounts.load_accounts(self.path)
                self.assertNotIn('sensitive', str(error.exception))

    def test_missing_environment_fails_before_applying_any_account(self):
        self.write({'password': 'sensitive'}, {'password_env': 'MISSING'})
        with patch.object(build, 'proot') as proot:
            with self.assertRaises(ValueError):
                build.apply_accounts('server', self.path)
            proot.assert_not_called()

    def test_defaults_lock_both_and_private_file_overrides(self):
        baseline = Path(self.tmp.name)/'default.json'
        baseline.write_text(json.dumps({'schema': 1, 'desktop':
                                        {'root': {'locked': True}, 'reimuks': {'locked': True}}}))
        with patch.object(accounts, 'DEFAULT_CONFIG', baseline), patch.object(accounts, 'LOCAL_CONFIG', self.path):
            self.assertEqual(accounts.load_accounts()['root'], ('locked', True))
            self.write({'password': 'local-root'}, {'password': 'local-user'})
            self.assertEqual(accounts.load_accounts()['reimuks'], ('password', 'local-user'))

    def test_applier_keeps_password_out_of_proot_argv(self):
        self.write({'password': 'root-secret'}, {'password': 'user-secret'})
        with patch.object(build, 'check_rootfs'), patch.object(build, 'profile_directory', return_value=Path(self.tmp.name)), patch.object(build, 'proot') as proot:
            build.apply_accounts('server', self.path)
        self.assertEqual(len(proot.call_args_list), 2)
        for call in proot.call_args_list:
            self.assertNotIn('secret', repr(call.args))
            self.assertTrue(call.kwargs['input'].endswith('\n'))


if __name__ == '__main__':
    unittest.main()
