from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import BaseModel, Field

Provider = Literal["f5", "qwen"]


class SynthesizeChannelRequest(BaseModel):
    channel_name: str
    text: str
    author: str = "unknown"
    user_id: int | None = None
    volume_level: float = Field(default=50.0, ge=0.0, le=100.0)
    tts_settings: dict[str, Any] = Field(default_factory=dict)
    word_filter: list[str] = Field(default_factory=list)
    blocked_users: list[str] = Field(default_factory=list)
    provider: Provider | None = None
    voice: str | None = None
    voice_map: dict[str, str] | None = None
    tenant_id: str | None = None

    def resolve_provider(self) -> Provider:
        if self.provider in {"f5", "qwen"}:
            return self.provider
        candidate = str(self.tts_settings.get("advanced_provider", "f5")).strip().lower()
        if candidate == "qwen":
            return "qwen"
        return "f5"

    def resolve_voice(self, provider: Provider) -> str:
        if self.voice and self.voice.strip():
            return self.voice.strip()
        if self.voice_map and provider in self.voice_map and self.voice_map[provider].strip():
            return self.voice_map[provider].strip()
        if provider == "qwen":
            fallback = str(self.tts_settings.get("qwen_voice", "")).strip()
            if fallback:
                return fallback
        fallback = str(self.tts_settings.get("voice", "")).strip()
        return fallback or ("default" if provider == "qwen" else "female_1")

    def resolve_tenant(self) -> str:
        if self.tenant_id and self.tenant_id.strip():
            return self.tenant_id.strip()
        if self.channel_name.strip():
            return f"channel:{self.channel_name.strip().lower()}"
        if self.user_id:
            return f"user:{self.user_id}"
        return "tenant:default"


class JobEnvelope(BaseModel):
    job_id: str
    provider: Provider
    tenant_id: str
    weight: float = Field(default=1.0, gt=0.0)
    cost: float = Field(default=1.0, gt=0.0)
    created_at: float = Field(default_factory=lambda: time.time())
    payload: SynthesizeChannelRequest
    voice: str


class NormalizedSynthesizeResponse(BaseModel):
    success: bool
    audio_url: str | None = None
    selected_voice: str | None = None
    voice: str | None = None
    tts_type: str
    duration: float | None = None
    error: str | None = None
    provider: Provider


class HealthResponse(BaseModel):
    status: str
    service: str
    redis: str | None = None
    scheduler: str | None = None

