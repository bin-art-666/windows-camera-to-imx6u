"""Pull latest camera JPEG. Standard library only, compatible with Python 3.5."""
from __future__ import print_function
import argparse
import os
import time
from urllib.request import urlopen

MAX_JPEG_BYTES = 4 * 1024 * 1024


def fetch_frame(url, timeout=5):
    with urlopen(url, timeout=timeout) as response:
        if response.headers.get_content_type() != 'image/jpeg':
            raise ValueError('Expected image/jpeg')
        sequence = response.headers.get('X-Frame-Sequence')
        jpeg = response.read(MAX_JPEG_BYTES + 1)
    if len(jpeg) > MAX_JPEG_BYTES:
        raise ValueError('JPEG exceeds 4 MiB limit')
    if not jpeg.startswith(b'\xff\xd8') or not jpeg.endswith(b'\xff\xd9'):
        raise ValueError('Incomplete JPEG')
    return sequence, jpeg


def save_latest(path, jpeg):
    temporary = path + '.tmp'
    try:
        with open(temporary, 'wb') as output:
            output.write(jpeg)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server', default='http://192.168.1.100:8080')
    parser.add_argument('--output', default='latest.jpg')
    parser.add_argument('--fps', type=float, default=5)
    parser.add_argument('--timeout', type=float, default=5)
    parser.add_argument('--max-frames', type=int, default=0, help='0 means continuous')
    parser.add_argument('--max-errors', type=int, default=0, help='0 means retry indefinitely')
    args = parser.parse_args()
    if args.fps <= 0 or args.timeout <= 0 or args.max_frames < 0 or args.max_errors < 0:
        parser.error('fps/timeout must be positive; frame/error limits must be nonnegative')
    output = os.path.abspath(args.output)
    if not os.path.isdir(os.path.dirname(output)):
        os.makedirs(os.path.dirname(output))
    url = args.server.rstrip('/') + '/frame.jpg'
    print('Pulling {} -> {} | Ctrl+C to stop'.format(url, output), flush=True)
    previous = None
    count = errors = consecutive_errors = 0
    started = last_report = time.monotonic()
    try:
        while not args.max_frames or count < args.max_frames:
            tick = time.monotonic()
            try:
                sequence, jpeg = fetch_frame(url, args.timeout)
                consecutive_errors = 0
                if sequence is None or sequence != previous:
                    save_latest(output, jpeg)
                    previous = sequence
                    count += 1
                    now = time.monotonic()
                    if count == 1 or now - last_report >= 5 or count == args.max_frames:
                        print('Received {} frames | average {:.2f} fps | JPEG {} bytes | sequence {}'.format(
                            count, count / max(now - started, 0.001), len(jpeg), sequence), flush=True)
                        last_report = now
            except (OSError, ValueError) as exc:
                errors += 1
                consecutive_errors += 1
                print('Receive error {}: {} (previous image may be stale)'.format(errors, exc), flush=True)
                if args.max_errors and consecutive_errors >= args.max_errors:
                    return 1
                time.sleep(1)
            time.sleep(max(0, 1.0 / args.fps - (time.monotonic() - tick)))
    except KeyboardInterrupt:
        print('\nStopped.', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
