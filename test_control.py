"""Windows interprocess lock test: stopping must work while launcher holds lock."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless(os.name == 'nt', 'Windows launcher test')
class ControlTests(unittest.TestCase):
    def test_stop_and_duplicate_start_under_active_lock(self):
        import msvcrt
        root = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory() as temporary:
            isolated = Path(temporary)
            for name in ('launch.py', 'stop.py', 'sender.py'):
                shutil.copyfile(root / name, isolated / name)
            for name in ('bin/camera_viewer_arm', 'board/run_viewer.sh', 'board/service.sh'):
                path = isolated / name
                path.parent.mkdir(exist_ok=True)
                path.write_bytes(b'test-placeholder')
            with open(isolated / '.launch.lock', 'w+b') as lock:
                lock.write(b'0'); lock.flush(); lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                stopped = subprocess.run([sys.executable, str(isolated / 'stop.py')], capture_output=True, text=True, timeout=10)
                self.assertEqual(stopped.returncode, 0, stopped.stderr)
                self.assertTrue((isolated / '.stop_requested').exists())
                duplicate = subprocess.run([sys.executable, str(isolated / 'launch.py')], capture_output=True, text=True, timeout=10)
                self.assertEqual(duplicate.returncode, 1)
                self.assertIn('already running', duplicate.stdout)


if __name__ == '__main__':
    unittest.main()
