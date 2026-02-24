from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse

from .adapters import F5Adapter, QwenAdapter
from .auth import verify_api_key
from .config import Settings, get_settings
from .redis_store import RedisJobStore
from .scheduler import Scheduler
from .schemas import HealthResponse, JobEnvelope, SynthesizeChannelRequest
from .storage.audio_store import AudioStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("tts-gateway")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = get_settings()
    app.state.settings = settings

    audio_store = AudioStore(settings.audio_path)
    store = RedisJobStore(
        redis_url=settings.redis_url,
        aging_factor=settings.wfq_aging_factor,
        candidate_window=settings.queue_candidate_window,
    )
    await store.connect()

    f5_adapter = F5Adapter(
        base_url=settings.f5_url,
        api_key=settings.f5_api_key,
        timeout_sec=settings.request_timeout_sec,
        retry_budget=settings.provider_retry_budget,
    )
    qwen_adapter = QwenAdapter(
        base_url=settings.qwen_url,
        api_key=settings.qwen_api_key,
        timeout_sec=settings.request_timeout_sec,
        retry_budget=settings.provider_retry_budget,
        url_policy=settings.qwen_url_policy,
        gateway_public_base_url=settings.public_base_url,
        audio_store=audio_store,
    )

    scheduler = Scheduler(
        store=store,
        adapters={"f5": f5_adapter, "qwen": qwen_adapter},
        lane_limits={
            "f5": settings.f5_lane_concurrency,
            "qwen": settings.qwen_lane_concurrency,
        },
        poll_ms=settings.scheduler_poll_ms,
        circuit_failure_threshold=settings.circuit_failure_threshold,
        circuit_recovery_sec=settings.circuit_recovery_sec,
    )
    await scheduler.start()

    app.state.audio_store = audio_store
    app.state.store = store
    app.state.scheduler = scheduler
    app.state.adapters = {"f5": f5_adapter, "qwen": qwen_adapter}

    try:
        yield
    finally:
        await scheduler.stop()
        for adapter in app.state.adapters.values():
            await adapter.close()
        await store.close()


app = FastAPI(title="tts-gateway", version="0.1.0", lifespan=lifespan)


@app.get("/health/live", response_model=HealthResponse)
async def health_live() -> HealthResponse:
    return HealthResponse(status="ok", service="tts-gateway")


@app.get("/health/ready", response_model=HealthResponse)
async def health_ready() -> HealthResponse:
    redis_ok = await app.state.store.ping()
    scheduler_ok = bool(app.state.scheduler.running)
    return HealthResponse(
        status="ok" if redis_ok and scheduler_ok else "degraded",
        service="tts-gateway",
        redis="ok" if redis_ok else "down",
        scheduler="running" if scheduler_ok else "stopped",
    )


@app.post("/api/tts/synthesize-channel", dependencies=[Depends(verify_api_key)])
async def synthesize_channel(payload: SynthesizeChannelRequest):
    blocked = {name.strip().lower() for name in payload.blocked_users if name and isinstance(name, str)}
    if payload.author.strip().lower() in blocked:
        return {
            "success": False,
            "audio_url": None,
            "voice": None,
            "selected_voice": None,
            "tts_type": "ai_f5",
            "duration": None,
            "error": "Author is blocked",
        }

    text = payload.text
    for word in payload.word_filter:
        if word:
            text = text.replace(word, "")

    provider = payload.resolve_provider()
    voice = payload.resolve_voice(provider)
    tenant_id = payload.resolve_tenant()
    weight = float(payload.tts_settings.get("tenant_weight") or 1.0)
    cost = float(max(1, len(text)))

    request_payload = payload.model_copy(update={"text": text})
    job_id = uuid.uuid4().hex
    job = JobEnvelope(
        job_id=job_id,
        provider=provider,
        tenant_id=tenant_id,
        weight=weight,
        cost=cost,
        payload=request_payload,
        voice=voice,
    )
    await app.state.store.enqueue(job)

    result = await app.state.store.wait_result(job_id, timeout_sec=app.state.settings.result_timeout_sec)
    if result is None:
        raise HTTPException(status_code=504, detail="Gateway timeout waiting provider result")

    return {
        "success": result.success,
        "audio_url": result.audio_url,
        "selected_voice": result.selected_voice or result.voice,
        "voice": result.voice or result.selected_voice,
        "tts_type": result.tts_type,
        "duration": result.duration,
        "error": result.error,
        "provider": result.provider,
    }


@app.get("/api/tts/audio/{filename}")
async def get_audio(filename: str):
    path = app.state.audio_store.resolve_path(filename)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Audio not found")
    return FileResponse(path)


@app.get("/")
async def root():
    return {"service": "tts-gateway", "status": "ok"}

