from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = Field("0.0.0.0", alias="TTS_GATEWAY_HOST")
    port: int = Field(8010, alias="TTS_GATEWAY_PORT")
    public_base_url: str = Field("http://localhost:8010", alias="TTS_GATEWAY_PUBLIC_BASE_URL")
    api_keys_raw: str = Field("", alias="TTS_GATEWAY_API_KEYS")
    base_dir: str = Field(".", alias="TTS_GATEWAY_BASE_DIR")

    redis_url: str = Field("redis://localhost:6379/0", alias="TTS_GATEWAY_REDIS_URL")
    result_timeout_sec: int = Field(30, alias="TTS_GATEWAY_RESULT_TIMEOUT_SEC")
    idempotency_ttl_sec: int = Field(60, alias="TTS_GATEWAY_IDEMPOTENCY_TTL_SEC")
    scheduler_poll_ms: int = Field(10, alias="TTS_GATEWAY_SCHEDULER_POLL_MS")
    wfq_aging_factor: float = Field(0.015, alias="TTS_GATEWAY_WFQ_AGING_FACTOR")

    f5_lane_concurrency: int = Field(2, alias="TTS_GATEWAY_F5_LANE_CONCURRENCY")
    qwen_lane_concurrency: int = Field(1, alias="TTS_GATEWAY_QWEN_LANE_CONCURRENCY")

    f5_url: str = Field("http://localhost:8011", alias="TTS_GATEWAY_F5_URL")
    f5_api_key: str = Field("", alias="TTS_GATEWAY_F5_API_KEY")
    qwen_url: str = Field("http://localhost:8012", alias="TTS_GATEWAY_QWEN_URL")
    qwen_api_key: str = Field("", alias="TTS_GATEWAY_QWEN_API_KEY")
    qwen_url_policy: str = Field("auto", alias="TTS_GATEWAY_QWEN_URL_POLICY")
    qwen_proxy_max_audio_bytes: int = Field(25_000_000, alias="TTS_GATEWAY_QWEN_PROXY_MAX_AUDIO_BYTES")

    audio_dir: str = Field("data/audio", alias="TTS_GATEWAY_AUDIO_DIR")

    request_timeout_sec: float = Field(20.0, alias="TTS_GATEWAY_REQUEST_TIMEOUT_SEC")
    provider_retry_budget: int = Field(1, alias="TTS_GATEWAY_PROVIDER_RETRY_BUDGET")
    queue_candidate_window: int = Field(10, alias="TTS_GATEWAY_QUEUE_CANDIDATE_WINDOW")
    max_input_text_length: int = Field(2000, alias="TTS_GATEWAY_MAX_INPUT_TEXT_LENGTH")
    tenant_rate_limit_per_minute: int = Field(0, alias="TTS_GATEWAY_TENANT_RATE_LIMIT_PER_MINUTE")

    circuit_failure_threshold: int = Field(5, alias="TTS_GATEWAY_CIRCUIT_FAILURE_THRESHOLD")
    circuit_recovery_sec: float = Field(20.0, alias="TTS_GATEWAY_CIRCUIT_RECOVERY_SEC")

    @property
    def api_keys(self) -> set[str]:
        return {item.strip() for item in self.api_keys_raw.split(",") if item.strip()}

    @property
    def base_path(self) -> Path:
        return Path(self.base_dir).resolve()

    @property
    def audio_path(self) -> Path:
        candidate = Path(self.audio_dir)
        if candidate.is_absolute():
            return candidate.resolve()
        return (self.base_path / candidate).resolve()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
