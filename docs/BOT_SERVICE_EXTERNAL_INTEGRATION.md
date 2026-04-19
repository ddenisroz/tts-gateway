# Bot Service External Integration

Этот документ нужен не обычному пользователю, а тому, кто запускает `tts-gateway` вместе с Paidviewer.

Если ты просто поднимаешь весь продукт, начни с `paidviewer_tools/docs/QUICKSTART.md` в основном репозитории.

## Что это за сервис

`tts-gateway` — это общий cloud-оркестратор для `f5` и `qwen`.

Официальный cloud-путь только один:

```text
bot_service -> tts-gateway -> provider runtime
```

Self-host трафик не должен идти сюда как основной сценарий.

## Что `tts-gateway` обязан уметь

- принимать запрос на synth
- проверять свою готовность
- держать очередь и fair scheduling
- вызывать нужный provider runtime
- возвращать `audio_url`, который можно безопасно отдать дальше в продукт

## Обязательные endpoints

- `POST /api/tts/synthesize-channel`
- `GET /health/live`
- `GET /health/ready`
- `GET /api/admin/stats`
- `GET /api/tts/jobs/{job_id}`

## Авторизация

Используется строгий API-key контракт:

- `Authorization: Bearer <key>`
- `X-API-Key: <key>`

Если ключ неверный, ожидаем:

- `401`
- `{"detail":"Invalid API key"}`

## Минимальный запрос

```json
{
  "channel_name": "my_channel",
  "text": "Привет, чат",
  "author": "viewer123"
}
```

В реальном проде `bot_service` обычно добавляет ещё:

- `provider`
- `request_id`
- `tenant_id`
- `tts_settings`
- `voice_map`
- `user_id`

## Успешный ответ

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

## Что важно в эксплуатации

- `bot_service` остаётся источником истины по настройкам и маршрутизации
- `tts-gateway` отвечает только за cloud-оркестрацию
- `audio_url` из ответа — это тот URL, который должен использовать runtime потребитель
- Redis для `tts-gateway` обязателен

## Минимальный cutover smoke

1. synth с `provider=f5` работает
2. synth с `provider=qwen` работает
3. async synth + polling работает
4. полученный `audio_url` реально воспроизводим
