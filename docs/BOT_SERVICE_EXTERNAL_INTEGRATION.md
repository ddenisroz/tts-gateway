# Bot Service External Integration

This document fixes the active integration contract between `paidviewer_tools/bot_service` and `tts-gateway`.

## Role

`tts-gateway` is the shared cloud orchestrator for both `f5` and `qwen`.

It is the only official cloud synth path:

`bot_service -> tts-gateway -> provider runtime`

Self-host traffic must not be routed here as the primary self-host contract.

## Required endpoints

- `POST /api/tts/synthesize-channel`
- `GET /health/live`
- `GET /health/ready`
- `GET /api/admin/stats`
- `GET /api/tts/jobs/{job_id}` for async polling

## Auth

Gateway accepts strict API-key auth:

- `Authorization: Bearer <key>`
- `X-API-Key: <key>`

Invalid key contract:

- `401`
- `{"detail":"Invalid API key"}`

## Request contract

Minimal request:

```json
{
  "channel_name": "my_channel",
  "text": "Привет, чат",
  "author": "viewer123"
}
```

Expected production request fields from `bot_service` include:

- `provider`
- `request_id`
- `tenant_id`
- `tts_settings`
- `voice_map`
- `user_id`
- `author`

## Response contract

Normalized success response:

```json
{
  "success": true,
  "audio_url": "http://tts-gateway:8010/api/tts/audio/abc.wav",
  "selected_voice": "female_1",
  "voice": "female_1",
  "tts_type": "ai_f5",
  "duration": 2.31,
  "error": null,
  "provider": "f5"
}
```

Async response:

```json
{
  "success": true,
  "queued": true,
  "job_id": "4f2d2c0e0e244d57a3f2e1b4dd7ab8b6",
  "status": "queued",
  "audio_url": null,
  "provider": "f5"
}
```

## Operational rules

- Gateway owns fairness, queueing, and provider runtime calls.
- `bot_service` remains the source of truth for user settings and routing policy.
- `bot_service` should use the returned gateway `audio_url` for playback.
- `request_id` / `event_id` should be forwarded for idempotency and tracing.

## Startup checks from `bot_service`

Before sending traffic:

1. `GET /health/live`
2. `GET /health/ready`
3. stop routing if `ready != ok`

## Required env in `bot_service`

- `TTS_GATEWAY_URL=http://tts-gateway:8010`
- `TTS_GATEWAY_API_KEY=...`
- `TTS_GATEWAY_TIMEOUT_SEC=40`
- `TTS_GATEWAY_RETRY_COUNT=1`

## Cutover smoke

1. `provider=f5` synth works.
2. `provider=qwen` synth works.
3. async synth + polling works.
4. returned `audio_url` is playable from the runtime that consumes it.
