"""Protocol tests use synthetic marker data, not camera verification."""
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import urlopen
from sender import LatestFrame, make_handler
from receiver import fetch_frame, save_latest


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.frames = LatestFrame()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(self.frames))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = 'http://127.0.0.1:{}'.format(self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def test_no_camera_and_recovery(self):
        with self.assertRaises(HTTPError) as caught:
            fetch_frame(self.url + '/frame.jpg')
        self.assertEqual(caught.exception.code, 503)
        self.frames.update(b'\xff\xd8test\xff\xd9', 320, 240)
        sequence, jpeg = fetch_frame(self.url + '/frame.jpg')
        self.assertEqual(sequence, '1')
        self.assertEqual(jpeg, b'\xff\xd8test\xff\xd9')
        self.frames.fail('disconnected')
        with self.assertRaises(HTTPError):
            fetch_frame(self.url + '/frame.jpg')

    def test_latest_only_and_atomic_save(self):
        for i in range(10):
            self.frames.update(b'\xff\xd8' + str(i).encode() + b'\xff\xd9', 320, 240)
        sequence, jpeg = fetch_frame(self.url + '/frame.jpg')
        self.assertEqual(sequence, '10')
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'latest.jpg')
            save_latest(path, jpeg)
            with open(path, 'rb') as source:
                self.assertEqual(source.read(), jpeg)
            self.assertFalse(os.path.exists(path + '.tmp'))

    def test_bad_jpeg_rejected(self):
        self.frames.update(b'invalid', 1, 1)
        with self.assertRaises(ValueError):
            fetch_frame(self.url + '/frame.jpg')

    def test_status(self):
        import json
        with urlopen(self.url + '/status') as response:
            status = json.load(response)
        self.assertEqual(status['sequence'], 0)
        self.assertIsNotNone(status['error'])


if __name__ == '__main__':
    unittest.main()
