import hashlib
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location(
    'parallel_fetch', Path(__file__).resolve().parents[1]/'scripts/parallel_fetch.py')
fetcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetcher)


class FetchRetryTests(unittest.TestCase):
    def test_timeout_preserves_progress_for_a_new_curl_process(self):
        data = b'complete authenticated package'
        filename = 'example_1_arm64.deb'
        plan = "'https://example.test/pool/"+filename+"' "+filename+' '+str(len(data))+' SHA256:unused\n'
        metadata = ('Package: example\nFilename: pool/'+filename+'\nSHA256: '+
                    hashlib.sha256(data).hexdigest()+'\n')
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            attempts = []

            def curl(command):
                partial = Path(command[command.index('--output')+1])
                self.assertEqual(command[command.index('--retry')+1], '0')
                self.assertEqual(command[command.index('--continue-at')+1], '-')
                attempts.append(command)
                if len(attempts) == 1:
                    partial.write_bytes(data[:9])
                    return subprocess.CompletedProcess(command, 28)
                self.assertEqual(partial.read_bytes(), data[:9])
                with partial.open('ab') as output:
                    output.write(data[9:])
                return subprocess.CompletedProcess(command, 0)

            with patch.object(fetcher.subprocess, 'check_output', side_effect=[plan, metadata]), \
                 patch.object(fetcher.subprocess, 'run', side_effect=curl):
                fetcher.prefetch(state, ['example'], workers=1)
            self.assertEqual(len(attempts), 2)
            self.assertEqual((state/'archives'/filename).read_bytes(), data)


if __name__ == '__main__':
    unittest.main()
