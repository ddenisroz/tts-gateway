# tts-gateway

Общий cloud TTS-шлюз для Paidviewer.

## Кому нужен этот репозиторий

Этот репозиторий нужен тому, кто поднимает облачный TTS-контур Paidviewer.

Если ты обычный пользователь Paidviewer и не обслуживаешь инфраструктуру, этот репозиторий тебе обычно не нужен.

## Роль в системе

`tts-gateway` — единственная официальная облачная точка синтеза для обоих провайдеров:

- `f5`
- `qwen`

Рабочий путь:

`bot_service -> tts-gateway -> provider runtime`

## Что делает gateway

- принимает запросы от `bot_service`
- ставит задания в очередь
- следит за fair usage и concurrency
- обращается к runtime F5/Qwen
- возвращает безопасный для воспроизведения `audio_url`

## Основные endpoints

- `POST /api/tts/synthesize-channel`
- `GET /health/live`
- `GET /health/ready`
- `GET /api/admin/stats`
- `GET /api/tts/jobs/{job_id}`

## Обязательные env

- `TTS_GATEWAY_API_KEYS`
- `TTS_GATEWAY_REDIS_URL`
- `TTS_GATEWAY_F5_URL`
- `TTS_GATEWAY_F5_API_KEY`
- `TTS_GATEWAY_QWEN_URL`
- `TTS_GATEWAY_QWEN_API_KEY`

## Быстрый запуск

Базовый runtime: Python `3.12`.

### Docker

```bash
docker network create tts-gateway-local
docker run -d --name tts-gateway-redis --network tts-gateway-local redis:7-alpine
docker build -t tts-gateway:local .
docker run --rm --network tts-gateway-local -p 127.0.0.1:8010:8010 \
  -e TTS_GATEWAY_API_KEYS=change-me \
  -e TTS_GATEWAY_REDIS_URL=redis://tts-gateway-redis:6379/0 \
  tts-gateway:local
```

### Локально без Docker

```bash
uv sync --python 3.12
uv run uvicorn app.main:app --host 0.0.0.0 --port 8010
```

## Базовая проверка

```bash
curl http://127.0.0.1:8010/health/live
curl http://127.0.0.1:8010/health/ready
```

## Важные замечания

- Redis обязателен.
- `tts-gateway` относится только к `cloud` mode.
- Это не self-host runtime и не user control plane.
- Подробный контракт с `bot_service` описан в `docs/BOT_SERVICE_EXTERNAL_INTEGRATION.md`.
