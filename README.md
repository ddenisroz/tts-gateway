# tts-gateway

Scheduler-first orchestrator for TTS providers.

## Docs

- Bot integration contract: `docs/BOT_SERVICE_EXTERNAL_INTEGRATION.md`

## Goals

- public bot contract compatibility:
  - `POST /api/tts/synthesize-channel`
  - `GET /api/tts/jobs/{job_id}` (optional async polling)
  - `GET /health/live`
  - `GET /health/ready`
  - `GET /api/admin/stats`
- adapters:
  - `F5Adapter` -> `f5-tts-service /v1/synthesize`
  - `QwenAdapter` -> `nano-qwen3tts-vllm` (`/api/prepare + /api/stream/{id}`)
- fairness:
  - Redis hot path
  - WFQ + aging scheduling
  - provider execution lanes (scheduler-first, no classic worker pool)
- speed-first defaults:
  - persistent HTTP clients
  - strict timeouts + retry budget
  - fast-fail + circuit breaker
  - Qwen URL policy `auto` (passthrough-first, proxy fallback)
  - idempotency support for retries (`request_id`/`message_id`/`event_id`)

## Notes

- All relative paths are resolved from `TTS_GATEWAY_BASE_DIR` (default `.`).
- `GET /api/admin/stats` exposes queue depth, job states, scheduler/circuit runtime snapshot, and request metrics.
- `TTS_GATEWAY_IDEMPOTENCY_TTL_SEC` is clamped to result TTL (`TTS_GATEWAY_RESULT_TIMEOUT_SEC + 30`) to avoid stale dedup keys.
- Auth is strict API key only (`TTS_GATEWAY_API_KEYS`), no JWT/no-anon mode.
- Proxy mode for Qwen limits buffered audio size via `TTS_GATEWAY_QWEN_PROXY_MAX_AUDIO_BYTES`.
- Text input is guarded by `TTS_GATEWAY_MAX_INPUT_TEXT_LENGTH`.
- Optional tenant rate limit is configured via `TTS_GATEWAY_TENANT_RATE_LIMIT_PER_MINUTE` (`0` disables).

## Run

```bash
uv sync
uv run uvicorn app.main:app --host 0.0.0.0 --port 8010
```

## Quick Checks

```bash
python scripts/load_test.py --url http://localhost:8010/api/tts/synthesize-channel
python scripts/fairness_probe.py --url http://localhost:8010/api/tts/synthesize-channel
```
