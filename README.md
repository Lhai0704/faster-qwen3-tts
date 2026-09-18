# faster-qwen3-tts

This repository is a fork of [andimarafioti/faster-qwen3-tts](https://github.com/andimarafioti/faster-qwen3-tts), plus a local Chinese voice-clone studio.

- Upstream library and original docs live in [`app/`](app/)
- Local setup and usage notes: [`使用说明.md`](使用说明.md)

## Quick start

See `使用说明.md`. Double-click `start.cmd`, then open http://127.0.0.1:7860

## What is not committed

Models, the embedded Python runtime, caches, generated audio, logs, backups, and everything under `test-voice/` (personal reference recordings) are gitignored and must stay local.
