"""Temporary speech never persists text/audio; cancellation releases the model lock."""
import contextlib
import io
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import numpy as np
import soundfile as sf
import local_app as app


class TemporaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'test-voice').mkdir()
        (self.root / 'generated').mkdir()
        sf.write(self.root / 'test-voice' / 'voice.wav', np.zeros(2400), 24000)
        self.stack = contextlib.ExitStack()
        self.stack.enter_context(patch.object(app, 'ROOT', self.root))
        self.stack.enter_context(patch.object(app, 'OUT', self.root / 'generated'))
        self.stack.enter_context(patch.object(app, 'references', return_value=['voice.wav']))
        self.stack.enter_context(patch.object(app, '_load_locked', return_value=False))
        self.model = Mock()
        self.model.generate_voice_clone_streaming.return_value = iter([(np.ones(2400, dtype=np.float32) * .1, 24000, {'total_steps_so_far': 12})])
        self.stack.enter_context(patch.object(app, 'MODEL', self.model))

    def tearDown(self):
        self.stack.close()
        self.tmp.cleanup()

    def test_temporary_does_not_concatenate_save_or_log_text(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), patch.object(app.np, 'concatenate', side_effect=AssertionError('must not accumulate')):
            result = app.generate('private conversation', 'voice.wav', persist=False)
        self.assertFalse(result['persisted'])
        self.assertEqual(list((self.root / 'generated').iterdir()), [])
        self.assertEqual(output.getvalue(), '')
        self.assertNotIn('text', result)

    def test_legacy_generation_still_saves_pair(self):
        with contextlib.redirect_stdout(io.StringIO()):
            result = app.generate('test', 'voice.wav')
        self.assertTrue((self.root / 'generated' / result['file']).exists())
        self.assertEqual(len(list((self.root / 'generated').iterdir())), 2)

    def test_cancel_during_audio_releases_lock_without_saving(self):
        cancel = threading.Event()
        with self.assertRaises(app.CancelledError):
            app.generate('test', 'voice.wav', persist=False, cancel=cancel, on_chunk=lambda *_: cancel.set())
        self.assertFalse(app.LOCK.locked())
        self.assertEqual(list((self.root / 'generated').iterdir()), [])

    def test_cancel_after_load_prevents_inference(self):
        cancel = threading.Event()
        with patch.object(app, '_load_locked', side_effect=lambda _: cancel.set()), self.assertRaises(app.CancelledError):
            app.generate('test', 'voice.wav', persist=False, cancel=cancel)
        self.model.generate_voice_clone_streaming.assert_not_called()
        self.assertFalse(app.LOCK.locked())

    def test_disconnect_cancels_temporary_and_cleans_registry(self):
        handler = object.__new__(app.Handler)
        handler.wfile = Mock()
        handler.wfile.write.side_effect = BrokenPipeError()
        with patch.object(handler, 'send_response'), patch.object(handler, 'send_header'), patch.object(handler, 'end_headers'):
            handler.stream_generate({'persist': False, 'task_id': 'disconnect', 'text': 'test', 'reference': 'voice.wav'})
        self.model.generate_voice_clone_streaming.assert_not_called()
        self.assertNotIn('disconnect', app.TASKS)

    def test_cancel_before_registration_is_remembered(self):
        app.cancel_task('early')
        handler = object.__new__(app.Handler)
        handler.wfile = io.BytesIO()
        with patch.object(handler, 'send_response'), patch.object(handler, 'send_header'), patch.object(handler, 'end_headers'):
            handler.stream_generate({'persist': False, 'task_id': 'early', 'text': 'test', 'reference': 'voice.wav'})
        self.assertIn(b'cancelled', handler.wfile.getvalue())
        self.model.generate_voice_clone_streaming.assert_not_called()

    def test_owned_service_does_not_leave_pid_file(self):
        marker = self.root / 'server.pid'
        with patch.object(app, 'PID_FILE', marker), patch.dict(app.os.environ, {'DESKAIDE_PARENT_PID': '123'}):
            app.write_pid()
        self.assertFalse(marker.exists())


if __name__ == '__main__':
    unittest.main()
