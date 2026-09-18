import base64
import io
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
import soundfile as sf
from studio import Library, Monitor, settings
from unittest.mock import patch


class StudioTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lib = Library(self.tmp.name)
        audio = io.BytesIO()
        sf.write(audio, np.zeros(2400), 24000, format='WAV')
        self.audio = base64.b64encode(audio.getvalue()).decode()

    def tearDown(self):
        self.tmp.cleanup()

    def test_multiple_references_roundtrip_and_edit(self):
        a = self.lib.save_reference(dict(name='人物 A', text='原文 A', audio=self.audio))
        b = self.lib.save_reference(dict(name='人物 B', text='原文 B', audio=self.audio))
        self.assertNotEqual(a['file'], b['file'])
        self.lib.save_reference(dict(file=a['file'], name='人物 A 修改', text='新原文'))
        reloaded = Library(self.tmp.name).references()
        self.assertEqual({r['text'] for r in reloaded}, {'新原文', '原文 B'})
        self.assertAlmostEqual(a['seconds'], .1)

    def test_invalid_audio_and_path_do_not_write(self):
        for data in [dict(name='bad', audio='!'), dict(name='bad', audio=base64.b64encode(b'not audio').decode()), dict(name='bad', file='../x.wav')]:
            with self.assertRaises(ValueError):
                self.lib.save_reference(data)
        self.assertEqual(self.lib.names(), [])

    def test_delete_preserves_pair_and_rejects_traversal(self):
        wav = self.lib.out / 'result.wav'
        wav.write_bytes(b'audio')
        meta = self.lib.out / 'result.wav.json'
        meta.write_text(json.dumps({'text': 'hello', 'settings': {'seed': 8}}))
        self.assertEqual(self.lib.history()[0]['settings']['seed'], 8)
        with self.assertRaises(ValueError):
            self.lib.delete('../result.wav')
        self.lib.delete('result.wav')
        self.assertEqual(self.lib.history(), [])
        self.assertEqual(len(list((self.lib.out / '.trash').glob('*/*'))), 2)

    def test_legacy_and_corrupt_history_metadata(self):
        (self.lib.out / 'old.wav').write_bytes(b'audio')
        (self.lib.out / 'old.wav.json').write_text('{invalid')
        self.assertEqual(self.lib.history()[0]['file'], 'old.wav')

    def test_permanent_delete_only_selected_pair(self):
        for name in ('selected', 'keep'):
            (self.lib.out / (name + '.wav')).write_bytes(b'audio')
            (self.lib.out / (name + '.wav.json')).write_text('{}')
        with self.assertRaises(ValueError):
            self.lib.delete('selected.wav', 'invalid')
        self.assertTrue((self.lib.out / 'selected.wav').exists())
        self.lib.delete('selected.wav', 'permanent')
        self.assertFalse((self.lib.out / 'selected.wav').exists())
        self.assertFalse((self.lib.out / 'selected.wav.json').exists())
        self.assertTrue((self.lib.out / 'keep.wav').exists())
        self.assertTrue((self.lib.out / 'keep.wav.json').exists())
        self.assertFalse((self.lib.out / '.trash').exists())

    def test_reused_model_does_not_replace_load_duration(self):
        monitor = Monitor()
        monitor.record_load('0.6B', 5.23)
        monitor.update(phase='loading', load_elapsed=None, completed=[])
        monitor.update(load_reused=True)
        monitor.update(phase='preparing')
        state = monitor.snapshot()
        self.assertEqual(state['last_load']['seconds'], 5.23)
        self.assertEqual(state['task']['completed'], ['loading'])
        self.assertIsNone(state['task']['load_elapsed'])
        monitor.update(phase='error', error='test')
        self.assertNotIn('preparing', monitor.snapshot()['task']['completed'])

    def test_cpu_still_sampled_when_gpu_unavailable(self):
        monitor = Monitor()
        with patch('studio.psutil.cpu_percent', return_value=23.5), patch('studio.subprocess.check_output', side_effect=OSError()), patch('studio.time.sleep', side_effect=[None, RuntimeError('stop')]):
            with self.assertRaises(RuntimeError):
                monitor.run()
        state = monitor.snapshot()
        self.assertEqual(state['cpu']['utilization'], 23.5)
        self.assertFalse(state['gpu']['available'])
        self.assertIsNone(state['telemetry'][0]['gpu_temperature'])
        self.assertEqual(state['telemetry'][0]['cpu_utilization'], 23.5)

    def test_validation_limits(self):
        for data in [{'temperature': 0}, {'top_p': float('nan')}, {'seed': 1.2}, {'max_new_tokens': 9999}, {'do_sample': 'false'}, {'language': 'unknown'}, {'instruct': 1}, {'top_k': True}]:
            with self.subTest(data=data), self.assertRaises(ValueError):
                settings(data)
        self.assertIsInstance(settings({'top_k': 50.0})['top_k'], int)
        self.assertEqual(settings({'seed': -1})['seed'], -1)


if __name__ == '__main__':
    unittest.main()
