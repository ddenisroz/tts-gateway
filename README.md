# tts-gateway

Scheduler-first orchestrator for TTS providers.

## Goals

- public bot contract compatibility:
  - `POST /api/tts/synthesize-channel`
  - `GET /health/live`
  - `GET /health/ready`
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
