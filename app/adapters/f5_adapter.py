from __future__ import annotations

import logging

from ..schemas import JobEnvelope, NormalizedSynthesizeResponse
from .base import ProviderAdapter, absolutize_audio_url

logger = logging.getLogger(__name__)


class F5Adapter(ProviderAdapter):
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout_sec: float,
        retry_budget: int,
    ) -> None:
        super().__init__(timeout_sec=timeout_sec, retry_budget=retry_budget)
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key.strip()

    async def synthesize(self, job: JobEnvelope) -> NormalizedSynthesizeResponse:
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "text": job.payload.text,
            "voice": job.voice,
            "tenant_id": job.tenant_id,
            "channel_name": job.payload.channel_name,
            "author": job.payload.author,
            "user_id": job.payload.user_id,
            "volume_level": job.payload.volume_level,
            "format": "wav",
            "metadata": {
                "gateway_job_id": job.job_id,
                "gateway_provider": "f5",
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
                audio_url = absolutize_audio_url(self.base_url, data.get("audio_url"))
                return NormalizedSynthesizeResponse(
                    success=True,
                    audio_url=audio_url,
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

