"""Exercise the real HTTP framing without loading a GPU model."""
import base64
import http.client
import json
import threading
import unittest
from unittest.mock import patch

import numpy as np
import local_app as app


class StreamingTests(unittest.TestCase):
    def setUp(self):
        self.server = app.Server(('127.0.0.1', 0), app.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.client = http.client.HTTPConnection(*self.server.server_address, timeout=5)

    def tearDown(self):
        self.client.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def test_first_chunk_arrives_before_generation_finishes(self):
        release = threading.Event()
        audio = np.array([0.1, -0.3, 0.9], dtype=np.float32)

        def generate(*args, on_chunk):
            on_chunk(audio, 24000)
            if not release.wait(5):
                raise RuntimeError('client did not receive audio during generation')
            return {'file': 'test.wav'}

        with patch.object(app, 'generate', side_effect=generate):
            self.client.request('POST', '/generate/stream', '{}')
            response = self.client.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(json.loads(response.readline())['type'], 'start')
            event = json.loads(response.readline())
            self.assertEqual(event['type'], 'audio')
            np.testing.assert_array_equal(np.frombuffer(base64.b64decode(event['pcm']), '<f4'), audio)
            release.set()
            self.assertEqual(json.loads(response.readline())['result']['file'], 'test.wav')
            self.assertEqual(response.read(), b'')

    def test_errors_are_framed_and_close_cleanly(self):
        for error in (ValueError('invalid'), app.BusyError('busy'), RuntimeError('failed')):
            with self.subTest(error=error), patch.object(app, 'generate', side_effect=error):
                self.client.request('POST', '/generate/stream', '{}')
                response = self.client.getresponse()
                events = [json.loads(line) for line in response.read().splitlines()]
                self.assertEqual(events[-1], {'type': 'error', 'error': str(error)})

    def test_origin_rejected_before_generation(self):
        with patch.object(app, 'generate') as generate:
            self.client.request('POST', '/generate/stream', '{}', {'Origin': 'https://example.org'})
            response = self.client.getresponse()
            self.assertEqual(response.status, 403)
            response.read()
            generate.assert_not_called()

    def test_disconnected_listener_does_not_abort_generation(self):
        handler = object.__new__(app.Handler)
        completed = []

        def generate(*args, on_chunk):
            on_chunk(np.zeros(12, dtype=np.float32), 24000)
            completed.append(True)
            return {'file': 'saved.wav'}

        from unittest.mock import Mock
        handler.wfile = Mock()
        handler.wfile.write.side_effect = BrokenPipeError()
        with patch.object(handler, 'send_response'), patch.object(handler, 'send_header'), \
                patch.object(handler, 'end_headers'), patch.object(app, 'generate', side_effect=generate):
            handler.stream_generate({})
        self.assertEqual(completed, [True])


if __name__ == '__main__':
    unittest.main()
