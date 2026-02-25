# Bot Service External Integration

Этот документ фиксирует контракт между `bot_service` и внешним TTS в Phase 1.
Внешний публичный сервис: `tts-gateway`.

## 1) Обязательные endpoint'ы (`tts-gateway`)

1. `POST /api/tts/synthesize-channel`
2. `GET /health/live`
3. `GET /health/ready`

Дополнительно:

1. `GET /health`
2. `GET /api/admin/stats`
3. `GET /api/tts/audio/{filename}`
4. `GET /api/tts/jobs/{job_id}` (для async-режима)

## 2) Auth контракт

Поддерживаются заголовки:

1. `Authorization: Bearer <key>`
2. `X-API-Key: <key>`

При неверном ключе: `401` + `{"detail":"Invalid API key"}`.

## 3) Контракт синтеза

### Request: `POST /api/tts/synthesize-channel`

Минимальный payload:

```json
{
  "channel_name": "my_channel",
  "text": "Привет, чат",
  "author": "viewer123"
}
```

Рекомендуемый payload из `bot_service`:

```json
{
  "channel_name": "my_channel",
  "text": "Текст для озвучки",
  "author": "viewer123",
  "request_id": "chatmsg-123456",
  "user_id": 42,
  "volume_level": 50.0,
  "tts_settings": {
    "advanced_provider": "f5",
    "tenant_weight": 1.0,
    "voice": "female_1",
    "voice_settings": {
      "cfg_strength": 2.0,
      "speed_preset": "normal",
      "remove_silence": false
    }
  },
  "word_filter": [],
  "blocked_users": [],
  "provider": "f5",
  "voice": null,
  "voice_map": {
    "f5": "female_1",
    "qwen": "default"
  },
  "tenant_id": "channel:my_channel",
  "async_mode": false
}
```

### Provider/voice resolution

Провайдер:

1. `provider` (если передан `f5|qwen`)
2. `tts_settings.advanced_provider`
3. fallback: `f5`

Голос:

1. `voice`
2. `voice_map[provider]`
3. `tts_settings.qwen_voice` (для `qwen`)
4. `tts_settings.voice`
5. fallback: `default` для `qwen`, `female_1` для `f5`

### Response (нормализованный)

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

### Async режим

Если в request передать `"async_mode": true`, gateway не ждет провайдера и сразу возвращает:

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

Дальше `bot_service` опрашивает `GET /api/tts/jobs/{job_id}`.
Если результат уже протух (TTL), polling вернет `410`.
`job_id` должен быть hex-строкой (uuid-like).

Особенности:

1. Если `author` находится в `blocked_users`, вернется `success=false` без исключения.
2. Если текст после фильтрации пустой, вернется `success=false`.
3. Если текст слишком длинный, вернется `success=false` (лимит `TTS_GATEWAY_MAX_INPUT_TEXT_LENGTH`).
4. Если gateway не дождался результата провайдера, вернется HTTP `504`.
5. При превышении tenant rate limit вернется HTTP `429` (если включен `TTS_GATEWAY_TENANT_RATE_LIMIT_PER_MINUTE`).
6. Для защиты от дублей при retry передавайте `request_id` (или `tts_settings.message_id`/`event_id`).
7. `idempotency`-ключ живет не дольше TTL результата (защита от stale dedup ключей).

`GET /api/admin/stats` отдает:

1. `queues` (глубина по провайдерам)
2. `jobs` (queued/in_progress/done)
3. `scheduler` (lane limits, in-flight, circuit state)
4. `metrics` (total/blocked/empty/timeout/idempotency/provider success-failure)

## 4) Что обязательно сделать в `bot_service`

1. Routing:
   - `f5|qwen` -> `tts-gateway /api/tts/synthesize-channel`
   - `gcloud` оставить на текущем внутреннем path
2. Хранить user-настройки как source of truth в БД `bot_service`:
   - `advanced_provider` (`f5|qwen|gcloud`)
   - `voice_map` (`{"f5":"...","qwen":"..."}`)
   - `voice_settings` (`cfg_strength`, `speed_preset`, `remove_silence`)
   - флаги и лимиты (`tts_enabled`, `daily_limit`, `max_text_length`)
3. Передавать в gateway:
   - `provider`
   - `voice_map`
   - `tenant_id` или `event/message id` для трассировки
4. На воспроизведении использовать ровно тот `audio_url`, который вернул gateway.

Важно: user state не хранится в `tts-gateway`.

## 5) Policy для клиента `bot_service` -> `tts-gateway`

1. Таймауты:
   - connect: `1-2s`
   - read: `35-45s` (должен быть больше `TTS_GATEWAY_RESULT_TIMEOUT_SEC`)
2. Retry:
   - только network error и `5xx`
   - не ретраить `4xx` (кроме `429`, если поддерживаете)
   - максимум 1 retry
3. Fallback:
   - при timeout/down gateway не ронять общий процесс бота
   - применить вашу политику: skip или fallback provider
4. Header policy:
   - использовать один стандартный заголовок: `Authorization: Bearer <TTS_GATEWAY_API_KEY>`

## 6) Startup checks в `bot_service`

Перед стартом чтения чата:

1. `GET /health/live`
2. `GET /health/ready`
3. если `ready != ok`, не отправлять трафик в gateway

## 7) Voice/Limits API (если бот управляет голосами)

Voice-management и limits сейчас находятся в `f5-tts-service` (compat layer), не в gateway:

1. `/api/tts/voices*`
2. `/api/tts/user/voices*`
3. `/api/tts/user/tts-limits*`
4. `/api/admin/voices*`

## 8) Минимальные env для `bot_service`

1. `TTS_GATEWAY_URL=http://tts-gateway:8010`
2. `TTS_GATEWAY_API_KEY=...`
3. `TTS_GATEWAY_TIMEOUT_SEC=40`
4. `TTS_GATEWAY_RETRY_COUNT=1`
5. `TTS_GATEWAY_MAX_INPUT_TEXT_LENGTH=2000`
6. `TTS_GATEWAY_TENANT_RATE_LIMIT_PER_MINUTE=0`

## 9) Quick check перед cutover

1. `GET /health/live` -> `status=ok`
2. `GET /health/ready` -> `status=ok`, `redis=ok`, `scheduler=running`
3. `POST /api/tts/synthesize-channel` для `provider=f5`
4. `POST /api/tts/synthesize-channel` для `provider=qwen`
5. `POST /api/tts/synthesize-channel` c `"async_mode": true` + polling `GET /api/tts/jobs/{job_id}`
6. Проверка, что `audio_url` реально воспроизводится в runtime

## 10) Что еще остается сделать (после Phase 1)

1. Перенести `gcloud` под gateway (сейчас остается в `bot_service`).
2. Добавить distributed tracing (`request_id` -> gateway -> provider) через OpenTelemetry.
3. Добавить автотесты контракта `bot_service` <-> `tts-gateway` в CI.
