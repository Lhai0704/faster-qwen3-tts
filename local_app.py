from pathlib import Path
import json, time, threading, traceback, hashlib, gc, os, sys
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, unquote
from contextlib import contextmanager
import secrets
import base64
from studio import Library, Monitor, settings, DEFAULTS, LANGUAGES, atomic_json
import numpy as np
import soundfile as sf
import torch
from faster_qwen3_tts import FasterQwen3TTS

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'generated'
OUT.mkdir(exist_ok=True)
PID_FILE = ROOT / 'server.pid'
MODEL_PATH_FILES = {'0.6B': 'model-path.txt', '1.7B': 'model-path-1.7B.txt'}
ALLOWED_ORIGINS = (None, 'http://127.0.0.1:7860', 'http://localhost:7860')
MODEL = None
MODEL_KEY = None
LOCK = threading.Lock()
SERVER = None
DEFAULT_TEXT = '你好，很高兴在这里遇见你。这是一段在本地电脑上生成的声音克隆测试。希望今天的你，也能拥有轻松愉快的好心情。'
LIBRARY = Library(ROOT)
MONITOR = Monitor()

class BusyError(Exception):
    pass

@contextmanager
def operation(phase, kind=None):
    if not LOCK.acquire(blocking=False):
        raise BusyError('已有任务正在运行，请等待完成。')
    started = time.monotonic()
    MONITOR.update(phase=phase, kind=kind or phase, busy=True, started=started, phase_started=started,
                   elapsed=0, audio_seconds=0, steps=0, load_elapsed=None, load_reused=False, completed=[], error=None)
    try:
        yield
    except Exception as exc:
        MONITOR.update(phase='error', error=str(exc))
        raise
    else:
        MONITOR.update(phase='done')
    finally:
        MONITOR.update(busy=False, elapsed=round(time.monotonic() - started, 2))
        LOCK.release()

def references():
    return LIBRARY.names()

def gpu_stats():
    if not torch.cuda.is_available():
        return {'used_mb': 0, 'reserved_mb': 0, 'allocated_mb': 0, 'total_mb': 0}
    allocated = round(torch.cuda.memory_allocated() / (1024 ** 2))
    reserved = round(torch.cuda.memory_reserved() / (1024 ** 2))
    try:
        free, total = torch.cuda.mem_get_info()
        used = round((total - free) / (1024 ** 2))
        total_mb = round(total / (1024 ** 2))
    except Exception:
        used = reserved
        total_mb = round(torch.cuda.get_device_properties(0).total_memory / (1024 ** 2))
    return {'used_mb': used, 'reserved_mb': reserved, 'allocated_mb': allocated, 'total_mb': total_mb}

def snapshot():
    return {'ready': MODEL is not None, 'active_model': MODEL_KEY, 'models': {key: (ROOT / filename).is_file() for key, filename in MODEL_PATH_FILES.items()}, **MONITOR.snapshot()}

def _clear_cuda():
    gc.collect()
    if not torch.cuda.is_available():
        return
    try:
        torch.cuda.synchronize()
    except Exception:
        pass
    torch.cuda.empty_cache()
    try:
        torch.cuda.ipc_collect()
    except Exception:
        pass
    gc.collect()
    torch.cuda.empty_cache()

def _release_graph(obj):
    if obj is None:
        return
    graph = getattr(obj, 'graph', None)
    if graph is not None:
        try:
            graph.reset()
        except Exception:
            pass
        obj.graph = None
        del graph
    for name, value in list(vars(obj).items()):
        if torch.is_tensor(value) or isinstance(value, (list, tuple, dict)):
            setattr(obj, name, None)

def _unload_locked():
    global MODEL, MODEL_KEY
    previous = MODEL_KEY
    if MODEL is not None:
        _release_graph(getattr(MODEL, 'predictor_graph', None))
        _release_graph(getattr(MODEL, 'talker_graph', None))
        MODEL.predictor_graph = None
        MODEL.talker_graph = None
        MODEL.model = None
        MODEL = None
    MODEL_KEY = None
    _clear_cuda()
    return previous

def _load_locked(model_key):
    global MODEL, MODEL_KEY
    if model_key not in MODEL_PATH_FILES:
        raise ValueError('请选择 0.6B 或 1.7B。')
    path_file = ROOT / MODEL_PATH_FILES[model_key]
    if not path_file.is_file():
        raise ValueError(f'{model_key} 模型尚未下载完成。')
    already = MODEL is not None and MODEL_KEY == model_key
    if already:
        MONITOR.update(load_reused=True)
        return False
    load_started = time.perf_counter()
    _unload_locked()
    model_path = path_file.read_text(encoding='utf-8').strip()
    MODEL = FasterQwen3TTS.from_pretrained(model_path, device='cuda', dtype=torch.bfloat16, max_seq_len=2048)
    MODEL_KEY = model_key
    elapsed = time.perf_counter() - load_started
    MONITOR.record_load(model_key, elapsed)
    MONITOR.update(load_elapsed=round(elapsed, 2))
    return True

def unload_model():
    with operation('unloading'):
        previous = _unload_locked()
        result = {'ok': True, 'unloaded': True, 'previous_model': previous}
        result.update(snapshot())
        print(json.dumps({'event': 'unload', **result}, ensure_ascii=False), flush=True)
        return result

def load_model(model_key):
    with operation('loading'):
        started = time.perf_counter()
        loaded = _load_locked(model_key)
        result = {'ok': True, 'loaded': loaded, 'elapsed': round(time.perf_counter() - started, 2)}
        result.update(snapshot())
        print(json.dumps({'event': 'load', **result}, ensure_ascii=False), flush=True)
        return result

def generate(text, ref_name, ref_text='', model_key='0.6B', params=None, on_chunk=None):
    if not isinstance(text, str) or not text.strip() or len(text) > 500:
        raise ValueError('请输入 1 到 500 字的文字。长文建议分段生成。')
    if not isinstance(ref_text, str) or len(ref_text) > 5000:
        raise ValueError('参考文字最多 5000 字。')
    config = settings(params or {})
    config['xvec_only'] = config['xvec_only'] or not bool(ref_text.strip())
    if config['seed'] == -1:
        config['seed'] = secrets.randbelow(2147483648)
    if ref_name not in references():
        raise ValueError('找不到参考音频。')
    with operation('loading', kind='generate'):
        request_started = time.perf_counter()
        switched = _load_locked(model_key)
        load_elapsed = round(time.perf_counter() - request_started, 2)
        MONITOR.update(phase='preparing')
        started = time.perf_counter()
        source = ROOT / 'test-voice' / ref_name
        ref_dir = ROOT / 'cache' / 'references'
        ref_dir.mkdir(parents=True, exist_ok=True)
        prepared = ref_dir / (hashlib.sha256(source.read_bytes()).hexdigest() + '.wav')
        if not prepared.exists():
            reference, sr = sf.read(str(source), dtype='float32')
            if reference.ndim > 1:
                reference = reference.mean(axis=1)
            sf.write(str(prepared), reference, sr, subtype='PCM_16')
        torch.manual_seed(config['seed'])
        kwargs = {k: v for k, v in config.items() if k != 'seed'}
        audio, samples, steps = [], 0, 0
        MONITOR.update(phase='encoding')
        for chunk, rate, timing in MODEL.generate_voice_clone_streaming(text=text.strip(), ref_audio=str(prepared), ref_text=ref_text.strip(), chunk_size=12, **kwargs):
            chunk = np.asarray(chunk, dtype=np.float32).reshape(-1)
            if not np.isfinite(chunk).all():
                raise RuntimeError('生成的音频无效，请重试。')
            if not chunk.size:
                continue
            audio.append(chunk)
            samples += len(chunk)
            steps = timing.get('total_steps_so_far', steps)
            MONITOR.update(phase='generating', audio_seconds=round(samples / rate, 2), steps=steps)
            if on_chunk:
                on_chunk(chunk, rate)
        if not audio:
            raise RuntimeError('未生成音频，请调整文字或参考素材后重试。')
        MONITOR.update(phase='saving')
        waveform = np.concatenate(audio)
        if not np.isfinite(waveform).all() or waveform.size == 0:
            raise RuntimeError('生成的音频无效，请重试。')
        name = time.strftime('%Y%m%d-%H%M%S') + f'-{model_key}-{time.time_ns() % 1000000:06d}.wav'
        sf.write(str(OUT / name), waveform, rate, subtype='PCM_16')
        result = {'file': name, 'url': '/audio/' + name, 'seconds': round(len(waveform)/rate, 2), 'elapsed': round(time.perf_counter()-started, 2), 'total_elapsed': round(time.perf_counter()-request_started, 2), 'model': model_key, 'model_loaded': switched, 'mode': '完整参考模式' if ref_text.strip() else '音色参考模式', 'sample_rate': rate, 'peak': float(np.max(np.abs(waveform))), 'text': text, 'reference': ref_name, 'ref_text': ref_text.strip(), 'seed': 42}
        result.update(seed=config['seed'], settings=config, load_elapsed=load_elapsed, truncated=steps >= config['max_new_tokens'], mode='音色参考模式' if config['xvec_only'] else '完整参考模式')
        atomic_json(OUT / (name + '.json'), result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return result

def schedule_shutdown():
    def stop():
        time.sleep(0.3)
        if SERVER is not None:
            SERVER.shutdown()
    threading.Thread(target=stop, daemon=True).start()

class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        if urlparse(self.path).path != '/status':
            super().log_message(format, *args)

    def send(self, status, data, content_type='application/json; charset=utf-8'):
        if not isinstance(data, bytes):
            data = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(data)
    def read_json(self):
        length = int(self.headers.get('Content-Length', 0) or 0)
        if length < 0 or length > (42 * 1024 * 1024 if urlparse(self.path).path == '/references' else 40000):
            raise ValueError('Request too large')
        if length == 0:
            return {}
        data = json.loads(self.rfile.read(length))
        if not isinstance(data, dict):
            raise ValueError('请求必须是 JSON 对象。')
        return data
    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        if path == '/':
            return self.send(200, (ROOT/'studio.html').read_bytes(), 'text/html; charset=utf-8')
        if path in ('/studio.css', '/studio.js', '/studio-monitor.js', '/studio-stream.js'):
            mime = 'text/css' if path.endswith('.css') else 'text/javascript'
            return self.send(200, (ROOT/path[1:]).read_bytes(), mime + '; charset=utf-8')
        if path == '/status':
            data = snapshot()
            data.update({'default_text': DEFAULT_TEXT, 'defaults': DEFAULTS, 'languages': LANGUAGES})
            return self.send(200, data)
        if path == '/library':
            return self.send(200, {'references': LIBRARY.references(), 'history': LIBRARY.history()})
        if path.startswith('/reference/'):
            name = path.removeprefix('/reference/')
            if name in references():
                mime = {'.wav': 'audio/wav', '.mp3': 'audio/mpeg', '.flac': 'audio/flac', '.ogg': 'audio/ogg'}[Path(name).suffix.lower()]
                return self.send(200, (LIBRARY.refs / name).read_bytes(), mime)
        if path.startswith('/audio/'):
            name = path.removeprefix('/audio/')
            if Path(name).name == name and name.endswith('.wav') and (OUT/name).is_file():
                return self.send(200, (OUT/name).read_bytes(), 'audio/wav')
        self.send(404, {'error': 'Not found'})
    def do_POST(self):
        path = urlparse(self.path).path
        if self.headers.get('Origin') not in ALLOWED_ORIGINS:
            return self.send(403, {'error': 'Origin rejected'})
        try:
            data = self.read_json()
            if path == '/references':
                return self.send(200, LIBRARY.save_reference(data))
            if path == '/history/delete':
                return self.send(200, LIBRARY.delete(data.get('file'), data.get('mode', 'trash')))
            if path == '/generate':
                return self.send(200, generate(data.get('text',''), data.get('reference',''), data.get('ref_text',''), data.get('model','0.6B'), data.get('settings', {})))
            if path == '/generate/stream':
                return self.stream_generate(data)
            if path == '/model':
                action = data.get('action')
                if action == 'unload':
                    return self.send(200, unload_model())
                if action == 'load':
                    return self.send(200, load_model(data.get('model','0.6B')))
                return self.send(400, {'error': '请选择 load 或 unload。'})
            if path == '/shutdown':
                result = unload_model()
                result['stopping'] = True
                self.send(200, result)
                schedule_shutdown()
                return
            self.send(404, {'error': 'Not found'})
        except (ValueError, BusyError) as exc:
            self.send(409 if isinstance(exc, BusyError) else 400, {'error': str(exc)})
        except Exception as exc:
            traceback.print_exc()
            self.send(500, {'error': str(exc)})

    def stream_generate(self, data):
        self.send_response(200)
        self.send_header('Content-Type', 'application/x-ndjson; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.close_connection = True
        connected = True

        def emit(event):
            nonlocal connected
            if connected:
                try:
                    self.wfile.write((json.dumps(event, ensure_ascii=False) + '\n').encode('utf-8'))
                    self.wfile.flush()
                except OSError:
                    # Finish saving the requested work even if the page closes.
                    connected = False

        def chunk(audio, rate):
            emit(dict(type='audio', sample_rate=rate,
                      pcm=base64.b64encode(audio.astype('<f4').tobytes()).decode('ascii')))

        emit(dict(type='start'))
        try:
            result = generate(data.get('text', ''), data.get('reference', ''),
                              data.get('ref_text', ''), data.get('model', '0.6B'),
                              data.get('settings', {}), on_chunk=chunk)
            emit(dict(type='done', result=result))
        except Exception as exc:
            if not isinstance(exc, (ValueError, BusyError)):
                traceback.print_exc()
            emit(dict(type='error', error=str(exc)))

class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

def write_pid():
    PID_FILE.write_text(str(os.getpid()), encoding='utf-8')

def clear_pid():
    try:
        if PID_FILE.is_file() and PID_FILE.read_text(encoding='utf-8').strip() == str(os.getpid()):
            PID_FILE.unlink()
    except OSError:
        pass

if __name__ == '__main__':
    if '--test' in sys.argv:
        generate(DEFAULT_TEXT, references()[0])
    else:
        threading.Thread(target=MONITOR.run, daemon=True).start()
        SERVER = Server(('127.0.0.1', 7860), Handler)
        write_pid()
        print('Open http://127.0.0.1:7860 . First generation loads the model.', flush=True)
        try:
            SERVER.serve_forever()
        finally:
            with LOCK:
                _unload_locked()
            clear_pid()
            print('Server stopped. GPU model released.', flush=True)
