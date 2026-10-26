"""Explicit hardware integration test: real PC camera, board decode, reconnect, cleanup."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sender import LatestFrame, capture_loop, make_handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--camera', type=int, default=0)
    args = parser.parse_args()
    import cv2
    options = ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5', '-o', 'HostKeyAlgorithms=+ssh-rsa',
               '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=' + str(ROOT / '.known_hosts')]

    def ssh(command):
        result = subprocess.run(['ssh'] + options + ['root@192.168.1.4', command],
                                text=True, capture_output=True, timeout=20)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        return result.stdout.strip()

    def metrics():
        return json.loads(ssh('cat /tmp/camera_transport/status.json'))

    def wait_for(predicate, seconds=12):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            current = metrics()
            if predicate(current):
                return current
            time.sleep(0.5)
        raise AssertionError('Timed out, last metrics: ' + json.dumps(current))

    frames, stop = LatestFrame(), threading.Event()
    config = SimpleNamespace(camera=args.camera, width=320, height=240, fps=10, quality=70)
    worker = threading.Thread(target=capture_loop, args=(frames, stop, config, cv2), daemon=True)
    server = None
    thread = None
    evidence = {}
    try:
        worker.start()
        camera_deadline = time.monotonic() + 15
        while frames.snapshot()[0] is None and time.monotonic() < camera_deadline:
            time.sleep(0.2)
        assert frames.snapshot()[0] is not None, frames.snapshot()[1]

        def start_http():
            http = ThreadingHTTPServer(('192.168.1.100', 8080), make_handler(frames))
            serving = threading.Thread(target=http.serve_forever, kwargs={'poll_interval': 0.1}, daemon=True)
            serving.start()
            return http, serving

        server, thread = start_http()
        ssh('sh /home/root/camera_transport/service.sh stop')
        ssh('sh /home/root/camera_transport/service.sh start --exit-after=60')
        evidence['initial_live'] = wait_for(lambda item: item['state'] == 'live' and item['frames'] >= 8)
        duplicate = ssh('sh /home/root/camera_transport/service.sh start')
        assert duplicate.startswith('Already running'), duplicate
        evidence['duplicate_start'] = duplicate
        previous = evidence['initial_live']['frames']
        server.shutdown(); server.server_close(); thread.join(); server = None
        evidence['disconnected'] = wait_for(lambda item: item['state'] == 'reconnecting' and item['frame_age_ms'] > 2500)
        server, thread = start_http()
        evidence['recovered'] = wait_for(lambda item: item['state'] == 'live' and item['frames'] > previous + 8)
        print('PASS: real camera, ARM JPEG decode/display, duplicate start, disconnect/stale detection, reconnect', flush=True)
    finally:
        evidence['stop'] = ssh('sh /home/root/camera_transport/service.sh stop')
        evidence['final_status'] = ssh('sh /home/root/camera_transport/service.sh status')
        evidence['desktop'] = ssh('for p in $(pidof QDesktop); do head -4 /proc/$p/status; done')
        stop.set()
        if server:
            server.shutdown(); server.server_close(); thread.join()
        worker.join(timeout=3)
        directory = ROOT / 'build' / 'validation'
        directory.mkdir(parents=True, exist_ok=True)
        (directory / 'reconnect.json').write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding='utf-8')
        print(json.dumps(evidence, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
