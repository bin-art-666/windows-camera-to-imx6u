"""Windows camera -> latest JPEG over HTTP. Python 3.9+."""
import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class LatestFrame:
    def __init__(self):
        self.lock = threading.Lock()
        self.jpeg = None
        self.sequence = 0
        self.captured_at = None
        self.error = 'Camera starting'
        self.width = self.height = 0

    def update(self, jpeg, width, height):
        with self.lock:
            self.jpeg = jpeg
            self.sequence += 1
            self.captured_at = time.time()
            self.width, self.height = width, height
            self.error = None

    def fail(self, message):
        with self.lock:
            self.error = message
            self.jpeg = None

    def snapshot(self):
        with self.lock:
            return self.jpeg, dict(sequence=self.sequence, captured_at=self.captured_at,
                                   width=self.width, height=self.height, error=self.error)


def make_handler(frames):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            self.connection.settimeout(5)
            path = self.path.split('?', 1)[0]
            jpeg, status = frames.snapshot()
            headers = {}
            if path == '/status':
                body = json.dumps(status).encode('utf-8')
                code, content_type = 200, 'application/json'
            elif path == '/frame.jpg':
                if jpeg is None:
                    body = b'Camera frame unavailable'
                    code, content_type = 503, 'text/plain'
                else:
                    body = jpeg
                    code, content_type = 200, 'image/jpeg'
                    headers['X-Frame-Sequence'] = str(status['sequence'])
                    headers['X-Captured-At'] = str(status['captured_at'])
            elif path == '/':
                body = (b'<!doctype html><meta charset="utf-8"><title>Camera Transport</title>'
                        b'<h2>Camera Transport</h2><p><a href="/status">Status</a></p>'
                        b'<img id="frame" style="max-width:100%" alt="Waiting for camera">'
                        b'<script>const f=document.getElementById("frame");'
                        b'function next(){setTimeout(()=>{f.src="/frame.jpg?t="+Date.now()},100)}'
                        b'f.onload=next;f.onerror=next;next();</script>')
                code, content_type = 200, 'text/html; charset=utf-8'
            else:
                body = b'Not found'
                code, content_type = 404, 'text/plain'
            try:
                self.send_response(code)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                for name, value in headers.items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(body)
            except (OSError, TimeoutError):
                pass
    return Handler


def capture_loop(frames, stop, args, cv2):
    interval = 1.0 / args.fps
    while not stop.is_set():
        cap = cv2.VideoCapture(args.camera, cv2.CAP_DSHOW)
        try:
            if not cap.isOpened():
                frames.fail('Cannot open camera; close other camera apps or change --camera')
                stop.wait(2)
                continue
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
            cap.set(cv2.CAP_PROP_FPS, args.fps)
            while not stop.is_set():
                started = time.monotonic()
                ok, frame = cap.read()
                if not ok:
                    frames.fail('Camera read failed; retrying')
                    stop.wait(1)
                    break
                height, width = frame.shape[:2]
                if width > args.width or height > args.height:
                    ratio = min(args.width / width, args.height / height)
                    frame = cv2.resize(frame, (max(1, int(width * ratio)), max(1, int(height * ratio))))
                    height, width = frame.shape[:2]
                ok, encoded = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, args.quality])
                if ok:
                    frames.update(encoded.tobytes(), width, height)
                else:
                    frames.fail('JPEG encoding failed')
                stop.wait(max(0, interval - (time.monotonic() - started)))
        except Exception as exc:
            frames.fail(str(exc))
            stop.wait(2)
        finally:
            cap.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='192.168.1.100')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--camera', type=int, default=0)
    parser.add_argument('--width', type=int, default=320)
    parser.add_argument('--height', type=int, default=240)
    parser.add_argument('--fps', type=float, default=10)
    parser.add_argument('--quality', type=int, default=70)
    args = parser.parse_args()
    if args.width < 1 or args.height < 1 or args.fps <= 0 or not 1 <= args.quality <= 100:
        parser.error('width/height/fps must be positive; quality must be 1..100')
    import cv2
    frames, stop = LatestFrame(), threading.Event()
    server = ThreadingHTTPServer((args.host, args.port), make_handler(frames))
    worker = threading.Thread(target=capture_loop, args=(frames, stop, args, cv2), daemon=True)
    worker.start()
    print('Preview: http://{}:{}/ | Ctrl+C to stop'.format(args.host, args.port), flush=True)
    print('Camera frames are sent without mirroring.', flush=True)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()
        worker.join(timeout=3)


if __name__ == '__main__':
    main()
