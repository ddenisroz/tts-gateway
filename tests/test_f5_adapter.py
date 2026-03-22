from __future__ import annotations

import httpx
import pytest

from app.adapters.f5_adapter import F5Adapter
from app.schemas import JobEnvelope, SynthesizeChannelRequest
from app.storage.audio_store import AudioStore


@pytest.mark.asyncio
async def test_f5_adapter_proxies_provider_audio_to_gateway_storage(tmp_path):

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/v1/synthesize":
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "audio_url": "/api/tts/audio/upstream.wav",
                    "voice": "voice_a",
                    "selected_voice": "voice_a",
                    "duration": 1.234,
                },
            )

        if request.method == "GET" and request.url.path == "/api/tts/audio/upstream.wav":
            assert request.headers["authorization"] == "Bearer f5-key"
            assert request.headers["x-api-key"] == "f5-key"
            return httpx.Response(
                200,
                content=b"wav-bytes",
                headers={"content-type": "audio/wav"},
            )

        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    adapter = F5Adapter(
        base_url="http://f5-service:8011",
        api_key="f5-key",
        timeout_sec=5.0,
        retry_budget=0,
        gateway_public_base_url="http://gateway:8010",
        audio_store=AudioStore(tmp_path),
    )
    await adapter.close()
    adapter.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    job = JobEnvelope(
        job_id="abc12345abc12345",
        provider="f5",
        tenant_id="channel:test",
        payload=SynthesizeChannelRequest(
            channel_name="test",
            text="hello",
            author="user",
            user_id=1,
            provider="f5",
        ),
        voice="voice_a",
    )

    try:
        result = await adapter.synthesize(job)
    finally:
        await adapter.close()

    assert result.success is True
    assert result.provider == "f5"
    assert result.audio_url is not None
    assert result.audio_url.startswith("http://gateway:8010/api/tts/audio/")
    assert "f5-service:8011" not in result.audio_url

    saved_files = list(tmp_path.iterdir())
    assert len(saved_files) == 1
    assert saved_files[0].read_bytes() == b"wav-bytes"
