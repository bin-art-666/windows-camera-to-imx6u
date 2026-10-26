"""Stop a running one-click session, or clean up an orphaned board service."""
import msvcrt
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent


def main():
    with open(ROOT / '.launch.lock', 'a+b') as lock:
        if os.fstat(lock.fileno()).st_size == 0:
            lock.write(b'0'); lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            (ROOT / '.stop_requested').write_text('stop', encoding='ascii')
            print('Stop requested. The launcher will stop both ends and restore the board desktop.')
            return 0
        # No launcher owns the lock; a board viewer may have outlived a crashed PC process.
        command = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5',
                   '-o', 'HostKeyAlgorithms=+ssh-rsa', '-o', 'StrictHostKeyChecking=accept-new',
                   '-o', 'UserKnownHostsFile=' + str(ROOT / '.known_hosts'), 'root@192.168.1.4',
                   'if [ -f /home/root/camera_transport/service.sh ]; then sh /home/root/camera_transport/service.sh stop; fi']
        return subprocess.run(command, timeout=20).returncode


if __name__ == '__main__':
    raise SystemExit(main())
