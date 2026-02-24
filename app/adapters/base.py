from __future__ import annotations

from abc import ABC, abstractmethod

import httpx

from ..schemas import JobEnvelope, NormalizedSynthesizeResponse


class ProviderAdapter(ABC):
    def __init__(self, *, timeout_sec: float, retry_budget: int) -> None:
        self.timeout_sec = timeout_sec
        self.retry_budget = max(0, retry_budget)
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_sec, connect=min(5.0, timeout_sec)),
            limits=httpx.Limits(max_connections=256, max_keepalive_connections=64),
            follow_redirects=True,
        )

    async def close(self) -> None:
        await self.client.aclose()

    @abstractmethod
    async def synthesize(self, job: JobEnvelope) -> NormalizedSynthesizeResponse:
        raise NotImplementedError


def absolutize_audio_url(base_url: str, raw_url: str | None) -> str | None:
    if not raw_url:
        return None
    if raw_url.startswith(("http://", "https://")):
        return raw_url
    if raw_url.startswith("/"):
        return f"{base_url.rstrip('/')}{raw_url}"
    return f"{base_url.rstrip('/')}/{raw_url.lstrip('/')}"

