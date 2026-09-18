"""Persistent studio library, validated generation settings and GPU telemetry."""
import base64
import io
import json
import math
import os
from pathlib import Path
import subprocess
import threading
import time
import uuid
from collections import deque

import soundfile as sf
import psutil

DEFAULTS = dict(language='Chinese', temperature=0.9, top_k=50, top_p=1.0,
                repetition_penalty=1.05, max_new_tokens=1200, seed=42,
                do_sample=True, xvec_only=False, instruct='')
LANGUAGES = ['Chinese', 'English', 'Japanese', 'Korean', 'German', 'French',
             'Russian', 'Portuguese', 'Spanish', 'Italian', 'Auto']


def settings(data):
    if not isinstance(data, dict):
        raise ValueError('参数必须是对象。')
    result = {**DEFAULTS, **{k: v for k, v in data.items() if k in DEFAULTS}}
    for key, low, high in [('temperature', .1, 2), ('top_k', 0, 200),
                           ('top_p', .01, 1), ('repetition_penalty', 1, 2),
                           ('max_new_tokens', 16, 1200), ('seed', -1, 2147483647)]:
        value = result[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f'{key} 必须在 {low} 至 {high} 之间。')
        if key in ('top_k', 'max_new_tokens', 'seed') and int(value) != value:
            raise ValueError(f'{key} 必须是整数。')
        if key in ('top_k', 'max_new_tokens', 'seed'):
            result[key] = int(value)
    if result['language'] not in LANGUAGES:
        raise ValueError('不支持的语言。')
    for key in ('do_sample', 'xvec_only'):
        if not isinstance(result[key], bool):
            raise ValueError(f'{key} 必须为布尔值。')
    if not isinstance(result['instruct'], str) or len(result['instruct']) > 300:
        raise ValueError('风格指令最多 300 字。')
    return result


def atomic_json(path, data):
    tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


class Library:
    def __init__(self, root):
        self.root = Path(root)
        self.refs = self.root / 'test-voice'
        self.out = self.root / 'generated'
        self.refs.mkdir(exist_ok=True)
        self.out.mkdir(exist_ok=True)
        self.index = self.refs / 'library.json'
        self.lock = threading.RLock()

    def names(self):
        return sorted(p.name for p in self.refs.iterdir() if p.suffix.lower() in ('.wav', '.mp3', '.flac', '.ogg'))

    def metadata(self):
        return json.loads(self.index.read_text(encoding='utf-8')) if self.index.exists() else {}

    def references(self):
        with self.lock:
            meta = self.metadata()
            result = []
            for name in self.names():
                item = dict(file=name, name=Path(name).stem, text='', seconds=None)
                item.update(meta.get(name, {}))
                result.append(item)
            return result

    def save_reference(self, data):
        name, transcript = data.get('name', ''), data.get('text', '')
        if not isinstance(name, str) or not name.strip() or len(name) > 120:
            raise ValueError('素材名称需要 1–120 字。')
        if not isinstance(transcript, str) or len(transcript) > 5000:
            raise ValueError('参考文字最多 5000 字。')
        with self.lock:
            filename = data.get('file')
            seconds = None
            raw = None
            if data.get('audio'):
                try:
                    raw = base64.b64decode(data['audio'], validate=True)
                    if len(raw) > 30 * 1024 * 1024:
                        raise ValueError('音频文件不能超过 30 MB。')
                    with sf.SoundFile(io.BytesIO(raw)) as audio:
                        seconds = len(audio) / audio.samplerate
                        if not 0 < seconds <= 180:
                            raise ValueError('参考音频需在 0–180 秒之间，推荐 5–30 秒。')
                        ext = {'WAV': '.wav', 'MP3': '.mp3', 'FLAC': '.flac', 'OGG': '.ogg'}.get(audio.format)
                        if ext is None:
                            raise ValueError('仅支持 WAV、MP3、FLAC 和 OGG。')
                    filename = uuid.uuid4().hex + ext
                except (RuntimeError, TypeError) as exc:
                    raise ValueError('无法读取该音频文件。') from exc
            elif filename not in self.names():
                raise ValueError('请选择或上传音频。')
            meta = self.metadata()
            item = dict(name=name.strip(), text=transcript.strip(), seconds=seconds or meta.get(filename, {}).get('seconds'))
            if raw is not None:
                (self.refs / filename).write_bytes(raw)
            meta[filename] = item
            atomic_json(self.index, meta)
            return dict(file=filename, **item)

    def history(self):
        with self.lock:
            result = []
            for path in sorted(self.out.glob('*.wav'), reverse=True):
                item = dict(file=path.name, url='/audio/' + path.name, text=path.stem)
                try:
                    saved = json.loads(path.with_suffix('.wav.json').read_text(encoding='utf-8'))
                    item.update({k: saved[k] for k in ('text', 'seconds', 'elapsed', 'total_elapsed', 'load_elapsed', 'model', 'reference', 'ref_text', 'seed', 'settings', 'mode', 'truncated') if k in saved})
                except (OSError, ValueError):
                    pass
                result.append(item)
            return result

    def delete(self, name, mode='trash'):
        with self.lock:
            if mode not in ('trash', 'permanent'):
                raise ValueError('请选择移入回收站或永久删除。')
            if not isinstance(name, str) or Path(name).name != name or not name.endswith('.wav') or not (self.out / name).is_file():
                raise ValueError('找不到生成记录。')
            paths = (self.out / name, self.out / (name + '.json'))
            # Only operate on the selected pair directly inside the output directory.
            if any(p.resolve().parent != self.out.resolve() for p in paths):
                raise ValueError('不允许操作输出目录之外的文件。')
            if mode == 'permanent':
                for path in paths:
                    path.unlink(missing_ok=True)
                return {'ok': True, 'mode': mode}
            trash = self.out / '.trash' / uuid.uuid4().hex
            trash.mkdir(parents=True)
            for path in paths:
                if path.exists():
                    path.replace(trash / path.name)
            return {'ok': True, 'mode': mode}


class Monitor:
    def __init__(self):
        self.lock = threading.Lock()
        self.task = dict(phase='idle', kind=None, busy=False, elapsed=0, audio_seconds=0,
                         steps=0, load_elapsed=None, load_reused=False, completed=[])
        self.gpu = dict(available=False)
        self.cpu = dict(utilization=None, cores=psutil.cpu_count(), temperature=None, power=None,
                        sensor_note='当前系统采集接口未提供 CPU 温度与功率')
        self.series = deque(maxlen=60)
        self.last_load = None

    def update(self, **values):
        with self.lock:
            if 'phase' in values and values['phase'] != self.task['phase']:
                previous = self.task['phase']
                if 'completed' not in values and previous in ('loading', 'preparing', 'encoding', 'generating', 'saving', 'unloading') and values['phase'] != 'error':
                    self.task['completed'] = [*self.task['completed'], previous]
                self.task['phase_started'] = time.monotonic()
            self.task.update(values)

    def record_load(self, model, elapsed):
        with self.lock:
            self.last_load = dict(model=model, seconds=round(elapsed, 2), at=time.time())

    def snapshot(self):
        with self.lock:
            task = dict(self.task)
            if task.get('busy'):
                task['elapsed'] = round(time.monotonic() - task['started'], 1)
                task['phase_elapsed'] = round(time.monotonic() - task.get('phase_started', task['started']), 1)
            return dict(task=task, gpu=dict(self.gpu), cpu=dict(self.cpu),
                        telemetry=list(self.series), last_load=self.last_load)

    def run(self):
        psutil.cpu_percent(interval=None)
        time.sleep(1)
        while True:
            started = time.monotonic()
            cpu_utilization = psutil.cpu_percent(interval=None)
            try:
                args = ['nvidia-smi', '--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw,fan.speed', '--format=csv,noheader,nounits']
                line = subprocess.check_output(args, text=True, timeout=3, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).splitlines()[0]
                values = [v.strip() for v in line.split(',')]
                gpu = dict(available=True, name=values[0], sampled_at=time.time())
                for key, value in zip(['utilization', 'used_mb', 'total_mb', 'temperature', 'power', 'fan'], values[1:]):
                    try:
                        gpu[key] = float(value)
                    except ValueError:
                        gpu[key] = None
            except (OSError, subprocess.SubprocessError, IndexError):
                gpu = dict(available=False)
            with self.lock:
                self.gpu = gpu
                self.cpu['utilization'] = cpu_utilization
                self.series.append(dict(at=time.time(), cpu_utilization=cpu_utilization,
                                        gpu_utilization=gpu.get('utilization'),
                                        gpu_temperature=gpu.get('temperature'), gpu_power=gpu.get('power'),
                                        gpu_memory=gpu.get('used_mb')))
            time.sleep(max(.1, 1 - (time.monotonic() - started)))
