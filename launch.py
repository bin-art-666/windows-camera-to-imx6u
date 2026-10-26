"""One command: start Windows camera, deploy ARM viewer, show it on board LCD."""
import argparse
import json
import msvcrt
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
from http.server import ThreadingHTTPServer
from sender import LatestFrame, capture_loop, make_handler

ROOT = Path(__file__).resolve().parent
REMOTE = '/home/root/camera_transport'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='192.168.1.100')
    parser.add_argument('--board', default='192.168.1.4')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--camera', type=int, default=0)
    parser.add_argument('--width', type=int, default=320)
    parser.add_argument('--height', type=int, default=240)
    parser.add_argument('--fps', type=float, default=10)
    parser.add_argument('--quality', type=int, default=70)
    parser.add_argument('--receive-fps', type=int, default=5)
    parser.add_argument('--max-frames', type=int, default=0, help='Board test frame limit')
    parser.add_argument('--duration', type=int, default=0, help='Board test time limit in seconds')
    parser.add_argument('--screenshot', action='store_true', help='Save board UI test screenshot in /tmp')
    args = parser.parse_args()
    if (args.width < 1 or args.height < 1 or args.fps <= 0 or not 1 <= args.quality <= 100
            or not 1 <= args.receive_fps <= 20 or args.duration < 0 or args.duration > 86400
            or args.max_frames < 0):
        parser.error('Invalid dimensions, fps, quality, or test limits')
    import ipaddress
    # Addresses are used in remote shell arguments: accept literal IPv4 only.
    ipaddress.IPv4Address(args.host)
    ipaddress.IPv4Address(args.board)
    for executable in ('ssh', 'scp'):
        if not shutil.which(executable):
            raise RuntimeError('Windows OpenSSH {} is missing'.format(executable))
    required = [ROOT / 'bin' / 'camera_viewer_arm', ROOT / 'board' / 'run_viewer.sh', ROOT / 'board' / 'service.sh']
    for path in required:
        if not path.is_file():
            raise RuntimeError('Missing {}; run tools/build_arm.sh in WSL first'.format(path))
    lockfile = open(ROOT / '.launch.lock', 'a+b')
    if os.fstat(lockfile.fileno()).st_size == 0:
        lockfile.write(b'0'); lockfile.flush()
    lockfile.seek(0)
    try:
        msvcrt.locking(lockfile.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        lockfile.close()
        raise RuntimeError('Another one-click camera session is already running')
    stop_request = ROOT / '.stop_requested'
    stop_request.unlink(missing_ok=True)
    ssh_options = ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5', '-o', 'ServerAliveInterval=5',
                   '-o', 'ServerAliveCountMax=2', '-o', 'HostKeyAlgorithms=+ssh-rsa',
                   '-o', 'StrictHostKeyChecking=accept-new', '-o', 'UserKnownHostsFile=' + str(ROOT / '.known_hosts')]
    destination = 'root@' + args.board

    def remote(command, check=True):
        result = subprocess.run(['ssh'] + ssh_options + [destination, command],
                                capture_output=True, text=True, timeout=25, encoding='utf-8', errors='replace')
        if check and result.returncode:
            raise RuntimeError('SSH command failed:\n' + result.stdout + result.stderr)
        return result

    frames, stop = LatestFrame(), threading.Event()
    server = worker = http_worker = None
    board_started = False
    try:
        import cv2
        server = ThreadingHTTPServer((args.host, args.port), make_handler(frames))
        http_worker = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.2}, daemon=True)
        worker = threading.Thread(target=capture_loop, args=(frames, stop, args, cv2), daemon=True)
        http_worker.start(); worker.start()
        print('Starting computer camera...', flush=True)
        deadline = time.monotonic() + 15
        while frames.snapshot()[0] is None and time.monotonic() < deadline:
            time.sleep(0.2)
        jpeg, camera_status = frames.snapshot()
        if jpeg is None:
            raise RuntimeError(camera_status['error'])
        print('Camera ready: {}x{} | http://{}:{}/'.format(camera_status['width'], camera_status['height'], args.host, args.port), flush=True)
        print('Deploying ARM viewer...', flush=True)
        remote('mkdir -p ' + REMOTE)
        remote('if [ -f {0}/service.sh ]; then sh {0}/service.sh stop; fi'.format(REMOTE))
        # Use legacy SCP to support older board SSH installations.
        result = subprocess.run(['scp', '-O'] + ssh_options + [str(p) for p in required] + [destination + ':' + REMOTE + '/'], timeout=40)
        if result.returncode:
            raise RuntimeError('SCP deployment failed')
        remote('chmod +x {0}/camera_viewer_arm {0}/run_viewer.sh {0}/service.sh'.format(REMOTE))
        options = '--server=http://{}:{} --fps={} --max-frames={} --exit-after={}'.format(
            args.host, args.port, args.receive_fps, args.max_frames, args.duration)
        if args.screenshot:
            options += ' --screenshot=/tmp/camera_transport/viewer.png'
        # Cleanup remains necessary if start succeeded remotely but the reply was lost.
        board_started = True
        print(remote('sh ' + REMOTE + '/service.sh start ' + options).stdout.strip(), flush=True)
        print('Board LCD preview started. Ctrl+C to stop both ends and restore the board desktop.', flush=True)
        while True:
            time.sleep(2)
            if stop_request.exists():
                print('Stop requested by stop_all.bat.', flush=True)
                break
            result = remote('sh ' + REMOTE + '/service.sh status')
            lines = result.stdout.strip().splitlines()
            print(result.stdout.strip(), flush=True)
            if lines and lines[0].startswith('Not running'):
                metrics = next((json.loads(line) for line in lines[1:] if line.startswith('{')), {})
                if args.max_frames and metrics.get('frames', 0) < args.max_frames:
                    raise RuntimeError('Board stopped before requested frame count; check viewer.log')
                if not metrics.get('frames', 0):
                    raise RuntimeError('Board stopped without receiving a valid frame')
                break
    except KeyboardInterrupt:
        print('\nStopping...', flush=True)
    finally:
        if board_started:
            try:
                result = remote('sh ' + REMOTE + '/service.sh stop', check=False)
                print(result.stdout.strip(), flush=True)
                if result.returncode:
                    print('Board stop needs checking: ' + result.stderr, flush=True)
            except Exception as exc:
                print('Could not contact board for cleanup: {}. Use stop_all.bat after network recovers.'.format(exc), flush=True)
        stop.set()
        if server:
            if http_worker and http_worker.is_alive():
                server.shutdown()
            server.server_close()
        if worker:
            worker.join(timeout=3)
        lockfile.close()
        stop_request.unlink(missing_ok=True)
        print('Windows camera service stopped.', flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('ERROR: {}'.format(exc), flush=True)
        raise SystemExit(1)
