# faster-qwen3-tts

This repository is a fork of [andimarafioti/faster-qwen3-tts](https://github.com/andimarafioti/faster-qwen3-tts), plus a local Chinese voice-clone studio.

- Upstream library and original docs live in [`app/`](app/)
- Local setup and usage notes: [`使用说明.md`](使用说明.md)

## Quick start

See `使用说明.md`. Double-click `start.cmd`, then open http://127.0.0.1:7860

## Listen while generating

Click **生成声音** to start generation and automatically hear each audio chunk as it arrives. The studio shows received audio and buffered duration, with pause/resume controls. Model loading and initial warmup still take time; playback buffers when generation falls behind.

The complete WAV and generation settings are saved to the local library for replay and download. Closing or refreshing the page stops the live preview; the server continues generating and saving the result while it remains running.

Use a browser with Web Audio and streaming fetch support, such as current Chrome or Edge. See [`使用说明.md`](使用说明.md) for details and measured results.

## Local regression checks

Run from the repository root with the project's Python environment installed:

```powershell
.\.venv\Scripts\python.exe -m unittest test_studio test_stream -v
.\.venv\Scripts\python.exe -m py_compile local_app.py studio.py
node --test test_stream_player.js
node --check studio.js
node --check studio-stream.js
```

The streaming tests use synthetic audio and mocked generation; they do not require loading a model or committing recordings.

## What is not committed

Models, the embedded Python runtime, caches, generated audio, logs, backups, machine-specific model paths, PID files, local environment/credential files, and everything under `test-voice/` (personal reference recordings) are gitignored and must stay local. Review the staged diff before committing; ignore rules do not remove files that Git already tracks.
