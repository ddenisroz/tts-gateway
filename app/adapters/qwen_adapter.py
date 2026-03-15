from __future__ import annotations

import ipaddress
import io
import logging
import wave
from urllib.parse import urlparse

import httpx

from ..schemas import JobEnvelope, NormalizedSynthesizeResponse
from ..storage.audio_store import AudioStore
from .base import ProviderAdapter

logger = logging.getLogger(__name__)


class QwenAdapter(ProviderAdapter):
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout_sec: float,
        retry_budget: int,
        url_policy: str,
        gateway_public_base_url: str,
        audio_store: AudioStore,
        max_proxy_audio_bytes: int,
    ) -> None:
        super().__init__(timeout_sec=timeout_sec, retry_budget=retry_budget)
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key.strip()
        self.url_policy = (url_policy or "auto").strip().lower()
        self.gateway_public_base_url = gateway_public_base_url.rstrip("/")
        self.audio_store = audio_store
        self.max_proxy_audio_bytes = max(1_000_000, int(max_proxy_audio_bytes))

    async def synthesize(self, job: JobEnvelope) -> NormalizedSynthesizeResponse:
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        settings = job.payload.tts_settings
        prepare_data = {
            "model": str(settings.get("qwen_model") or "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"),
            "text": job.payload.text,
            "language": str(settings.get("qwen_language") or "Russian"),
            "temperature": str(settings.get("qwen_temperature") or 0.9),
            "instruction": str(settings.get("qwen_instruction") or ""),
            "speaker": job.voice,
            "tenant_id": job.tenant_id,
            "channel_name": job.payload.channel_name,
            "author": job.payload.author,
            "user_id": str(job.payload.user_id or ""),
            "request_id": str(job.payload.request_id or ""),
            "event_id": str(settings.get("event_id") or settings.get("source_message_id") or ""),
        }

        prepare_url = f"{self.base_url}/api/prepare"
        stream_id: str | None = None
        last_error = "unknown qwen error"
        for attempt in range(self.retry_budget + 1):
            try:
                prepare_resp = await self.client.post(prepare_url, data=prepare_data, headers=headers)
                if prepare_resp.status_code != 200:
                    last_error = f"qwen prepare status={prepare_resp.status_code}"
                    continue
                data = prepare_resp.json()
                stream_id = data.get("stream_id")
                if not stream_id:
                    last_error = "qwen prepare missing stream_id"
                    continue
                break
            except Exception as error:
                last_error = str(error)
                logger.warning("Qwen prepare attempt %s failed: %s", attempt + 1, error)

        if not stream_id:
            return self._failed(job, last_error)

        stream_url = f"{self.base_url}/api/stream/{stream_id}"
        policy = self.url_policy
        if policy not in {"auto", "passthrough", "proxy"}:
            policy = "auto"

        if policy == "passthrough" or (policy == "auto" and _looks_publicly_reachable(stream_url)):
            return NormalizedSynthesizeResponse(
                success=True,
                audio_url=stream_url,
                selected_voice=job.voice,
                voice=job.voice,
                tts_type="ai_qwen",
                duration=None,
                error=None,
                provider="qwen",
            )

        # Proxy fallback: download audio in-gateway and return gateway URL.
        try:
            timeout = httpx.Timeout(max(self.timeout_sec * 3, 90.0), connect=min(5.0, self.timeout_sec))
            audio_bytes = bytearray()
            content_type = ""
            async with self.client.stream("GET", stream_url, headers=headers, timeout=timeout) as response:
                if response.status_code != 200:
                    await self._cancel(stream_id, headers)
                    return self._failed(job, f"qwen stream status={response.status_code}")
                content_type = str(response.headers.get("content-type") or "")
                async for chunk in response.aiter_bytes():
                    if not chunk:
                        continue
                    audio_bytes.extend(chunk)
                    if len(audio_bytes) > self.max_proxy_audio_bytes:
                        await self._cancel(stream_id, headers)
                        return self._failed(job, f"qwen stream too large ({self.max_proxy_audio_bytes} bytes limit)")
            if not audio_bytes:
                await self._cancel(stream_id, headers)
                return self._failed(job, "qwen stream is empty")
            payload = bytes(audio_bytes)
            suffix = _detect_audio_suffix(content_type, payload)
            if suffix is None:
                await self._cancel(stream_id, headers)
                return self._failed(job, "qwen stream payload is not recognized as audio")
            filename = self.audio_store.save_bytes(payload, suffix=suffix)
            duration = _audio_duration_or_none(payload, suffix)
            return NormalizedSynthesizeResponse(
                success=True,
                audio_url=f"{self.gateway_public_base_url}/api/tts/audio/{filename}",
                selected_voice=job.voice,
                voice=job.voice,
                tts_type="ai_qwen",
                duration=duration,
                error=None,
                provider="qwen",
            )
        except Exception as error:
            await self._cancel(stream_id, headers)
            return self._failed(job, str(error))

    async def _cancel(self, stream_id: str, headers: dict[str, str]) -> None:
        try:
            await self.client.post(f"{self.base_url}/api/cancel/{stream_id}", headers=headers)
        except Exception:
            return

    @staticmethod
    def _failed(job: JobEnvelope, error: str) -> NormalizedSynthesizeResponse:
        return NormalizedSynthesizeResponse(
            success=False,
            audio_url=None,
            selected_voice=job.voice,
            voice=job.voice,
            tts_type="ai_qwen",
            duration=None,
            error=error,
            provider="qwen",
        )


def _wav_duration_or_none(payload: bytes) -> float | None:
    try:
        with wave.open(io.BytesIO(payload), "rb") as wav:
            frames = wav.getnframes()
            rate = wav.getframerate()
            if rate <= 0:
                return None
            return round(frames / float(rate), 3)
    except Exception:
        return None


def _audio_duration_or_none(payload: bytes, suffix: str) -> float | None:
    normalized = str(suffix or "").strip().lower()
    if normalized != ".wav":
        return None
    return _wav_duration_or_none(payload)


def _detect_audio_suffix(content_type: str, payload: bytes) -> str | None:
    ct = str(content_type or "").lower()
    if "audio/wav" in ct or "audio/x-wav" in ct or "audio/wave" in ct:
        return ".wav"
    if "audio/mpeg" in ct or "audio/mp3" in ct:
        return ".mp3"
    if "audio/ogg" in ct:
        return ".ogg"
    if "audio/flac" in ct:
        return ".flac"
    if "audio/aac" in ct:
        return ".aac"
    if "audio/mp4" in ct or "audio/x-m4a" in ct:
        return ".m4a"
    if "audio/aiff" in ct:
        return ".aiff"
    if "audio/basic" in ct:
        return ".au"
    if "audio/x-ms-wma" in ct:
        return ".wma"

    header = payload[:16]
    if len(header) >= 12 and header.startswith(b"RIFF") and header[8:12] == b"WAVE":
        return ".wav"
    if header.startswith(b"ID3") or (len(header) > 1 and header[0] == 0xFF and (header[1] & 0xE0) == 0xE0):
        return ".mp3"
    if header.startswith(b"OggS"):
        return ".ogg"
    if header.startswith(b"fLaC"):
        return ".flac"
    if len(header) >= 8 and header[4:8] == b"ftyp":
        return ".m4a"
    if header.startswith(bytes.fromhex("3026B2758E66CF11")):
        return ".wma"
    if header.startswith(b"FORM") and len(header) >= 12 and header[8:12] in {b"AIFF", b"AIFC"}:
        return ".aiff"
    if header.startswith(b".snd"):
        return ".au"
    return None


def _looks_publicly_reachable(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").strip().lower()
    if not host or host in {"localhost", "127.0.0.1", "::1", "host.docker.internal"}:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        # hostname (DNS) - assume externally reachable
        return True
    return not (ip.is_loopback or ip.is_private or ip.is_link_local)
