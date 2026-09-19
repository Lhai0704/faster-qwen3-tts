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
.\.venv\Scripts\python.exe -m unittest test_studio test_stream test_temporary -v
.\.venv\Scripts\python.exe -m py_compile local_app.py studio.py
node --test test_stream_player.js
node --check studio.js
node --check studio-stream.js
```

The streaming tests use synthetic audio and mocked generation; they do not require loading a model or committing recordings.

## What is not committed

Models, the embedded Python runtime, caches, generated audio, logs, backups, machine-specific model paths, PID files, local environment/credential files, and everything under `test-voice/` (personal reference recordings) are gitignored and must stay local. Review the staged diff before committing; ignore rules do not remove files that Git already tracks.

## DeskAide 临时播报接口

DeskAide 可以复用本服务，在对话中逐句请求流式音频。原网页生成与保存行为保持不变。

- `GET /status` 增加 `service: fast-qwen3-tts`、`api_version: 1`、`instance_id` 和能力 `temporary_stream`、`cancel_task`。忙碌状态仍在 `task.busy`。
- `GET /references` 只返回 `{references: [...]}`，含 `file`、`name` 和对应参考 `text`，不读取作品历史。
- `POST /generate/stream` 保留 `text/reference/ref_text/model/settings`，新增 `persist: false` 和必填唯一 `task_id` 以启用临时播报；单次文本仍限制 500 字。
- 响应为 NDJSON：`start`、`audio`（`sample_rate` 与 Base64 小端 Float32 单声道 `pcm`）、`done` 或 `error`。临时 `done.result` 不含文件 URL 或正文；取消返回 `cancelled`。
- `POST /cancel` 接收 `{task_id: "..."}`，只取消对应临时任务；允许取消请求比生成请求先到达。
- 临时模式不累积完整音频、不写作品 WAV/JSON、不输出生成正文日志；参考素材缓存可以复用。断开连接或取消后，在加载结束或分块检查点释放生成锁，无法即时中断正在执行的 GPU 运算。
- DeskAide 自启时传入 `DESKAIDE_PARENT_PID`，服务持有该父进程的 Windows 句柄；父进程退出即结束服务，包括模型加载期间。手动启动没有此归属关系。自启模式不创建可能过期的 `server.pid`。
- 请求仍只允许原本的本地来源；桌面应用应通过后端 HTTP 连接，不开放跨域或远程监听。

接口检查：`.\.venv\Scripts\python.exe -m unittest test_studio test_stream test_temporary -v`，播放器检查：`node test_stream_player.js`。
