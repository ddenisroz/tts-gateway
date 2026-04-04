# tts-gateway

Shared cloud TTS orchestrator for Paidviewer.

## Production role

`tts-gateway` is the only official cloud synth entry for both `f5` and `qwen`.

Runtime path:

`bot_service -> tts-gateway -> provider runtime`

## Required public endpoints

- `POST /api/tts/synthesize-channel`
- `GET /health/live`
- `GET /health/ready`
- `GET /api/admin/stats`
- `GET /api/tts/jobs/{job_id}` for async polling

## Paidviewer contract

- strict API-key auth only
- no user settings stored in gateway
- gateway returns the playback-safe `audio_url`
- gateway is responsible for queueing, fairness, and provider runtime calls

## Required env

- `TTS_GATEWAY_API_KEYS`
- `TTS_GATEWAY_REDIS_URL`
- `TTS_GATEWAY_F5_URL`
- `TTS_GATEWAY_F5_API_KEY`
- `TTS_GATEWAY_QWEN_URL`
- `TTS_GATEWAY_QWEN_API_KEY`

## Run

```bash
uv sync
uv run uvicorn app.main:app --host 0.0.0.0 --port 8010
```

## Quick checks

```bash
curl http://127.0.0.1:8010/health/live
curl http://127.0.0.1:8010/health/ready
```

## Notes

- Redis is mandatory.
- `tts-gateway` is cloud-only. It is not the self-host runtime path.
- The detailed bot-service contract is documented in `docs/BOT_SERVICE_EXTERNAL_INTEGRATION.md`.
