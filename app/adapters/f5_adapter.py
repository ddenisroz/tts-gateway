from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urlparse

from ..schemas import JobEnvelope, NormalizedSynthesizeResponse
from ..storage.audio_store import AudioStore
from .base import ProviderAdapter, absolutize_audio_url

logger = logging.getLogger(__name__)


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    normalized = str(value or "").strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off", ""}:
        return False
    return bool(value)


class F5Adapter(ProviderAdapter):
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout_sec: float,
        retry_budget: int,
        gateway_public_base_url: str,
        audio_store: AudioStore,
    ) -> None:
        super().__init__(timeout_sec=timeout_sec, retry_budget=retry_budget)
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key.strip()
        self.gateway_public_base_url = gateway_public_base_url.rstrip("/")
        self.audio_store = audio_store

    async def synthesize(self, job: JobEnvelope) -> NormalizedSynthesizeResponse:
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
            headers["X-API-Key"] = self.api_key

        settings = job.payload.tts_settings if isinstance(job.payload.tts_settings, dict) else {}
        voice_settings = settings.get("voice_settings", {}) if isinstance(settings.get("voice_settings"), dict) else {}
        cfg_strength = voice_settings.get("cfg_strength", settings.get("cfg_strength"))
        speed_preset = voice_settings.get("speed_preset", settings.get("speed_preset"))
        remove_silence = _as_bool(voice_settings.get("remove_silence", settings.get("remove_silence", False)))

        payload = {
            "text": job.payload.text,
            "voice": job.voice,
            "tenant_id": job.tenant_id,
            "channel_name": job.payload.channel_name,
            "author": job.payload.author,
            "user_id": job.payload.user_id,
            "volume_level": job.payload.volume_level,
            "format": "wav",
            "request_id": job.payload.request_id,
            "event_id": str(settings.get("event_id") or settings.get("source_message_id") or "") or None,
            "cfg_strength": cfg_strength,
            "speed_preset": speed_preset,
            "remove_silence": remove_silence,
            "metadata": {
                "gateway_job_id": job.job_id,
                "gateway_provider": "f5",
                "request_id": job.payload.request_id,
                "event_id": str(settings.get("event_id") or settings.get("source_message_id") or "") or None,
                "cfg_strength": cfg_strength,
                "speed_preset": speed_preset,
                "remove_silence": remove_silence,
            },
        }

        url = f"{self.base_url}/v1/synthesize"
        last_error = "unknown f5 error"
        for attempt in range(self.retry_budget + 1):
            try:
                response = await self.client.post(url, json=payload, headers=headers)
                if response.status_code != 200:
                    last_error = f"f5 status={response.status_code}"
                    continue

                data = response.json()
                if not data.get("success"):
                    last_error = str(data.get("error") or "f5 returned success=false")
                    continue
                upstream_audio_url = absolutize_audio_url(self.base_url, data.get("audio_url"))
                if not upstream_audio_url:
                    last_error = "f5 missing audio_url"
                    continue
                audio_response = await self.client.get(upstream_audio_url, headers=headers)
                if audio_response.status_code != 200:
                    last_error = f"f5 audio status={audio_response.status_code}"
                    continue
                audio_bytes = audio_response.content
                if not audio_bytes:
                    last_error = "f5 audio payload is empty"
                    continue
                suffix = Path(urlparse(upstream_audio_url).path).suffix.lower()
                if suffix not in {".wav", ".mp3", ".ogg", ".flac", ".m4a", ".aac", ".aiff", ".au", ".wma"}:
                    suffix = ".wav"
                filename = self.audio_store.save_bytes(audio_bytes, suffix=suffix)
                return NormalizedSynthesizeResponse(
                    success=True,
                    audio_url=f"{self.gateway_public_base_url}/api/tts/audio/{filename}",
                    selected_voice=data.get("selected_voice") or data.get("voice") or job.voice,
                    voice=data.get("voice") or data.get("selected_voice") or job.voice,
                    tts_type="ai_f5",
                    duration=data.get("duration"),
                    error=None,
                    provider="f5",
                )
            except Exception as error:
                last_error = str(error)
                logger.warning("F5 adapter attempt %s failed: %s", attempt + 1, error)

        return NormalizedSynthesizeResponse(
            success=False,
            audio_url=None,
            selected_voice=job.voice,
            voice=job.voice,
            tts_type="ai_f5",
            duration=None,
            error=last_error,
            provider="f5",
        )
