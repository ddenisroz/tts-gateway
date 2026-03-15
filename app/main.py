from __future__ import annotations

import logging
import mimetypes
import re
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse

from .adapters import F5Adapter, QwenAdapter
from .auth import verify_api_key
from .config import Settings, get_settings
from .metrics import GatewayMetrics
from .redis_store import RedisJobStore
from .scheduler import Scheduler
from .schemas import HealthResponse, JobEnvelope, NormalizedSynthesizeResponse, SynthesizeChannelRequest
from .storage.audio_store import AudioStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("tts-gateway")
JOB_ID_RE = re.compile(r"^[0-9a-f]{16,64}$")


async def _runtime_health_payload() -> dict[str, str]:
    redis_ok = await app.state.store.ping()
    scheduler_ok = bool(app.state.scheduler.running)
    return {
        "status": "ok" if redis_ok and scheduler_ok else "degraded",
        "service": "tts-gateway",
        "redis": "ok" if redis_ok else "down",
        "scheduler": "running" if scheduler_ok else "stopped",
    }


async def _require_runtime_ready() -> None:
    health = await _runtime_health_payload()
    if health["status"] != "ok":
        raise HTTPException(
            status_code=503,
            detail={
                "code": "gateway_runtime_unavailable",
                "message": "tts-gateway is not ready to process synthesis requests.",
                "redis": health["redis"],
                "scheduler": health["scheduler"],
            },
        )


def _result_to_payload(result: NormalizedSynthesizeResponse) -> dict[str, object | None]:
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


def _pending_payload(*, provider: str, job_id: str, state: str = "queued") -> dict[str, object | None]:
    resolved_provider = provider if provider in {"f5", "qwen"} else "unknown"
    if resolved_provider == "qwen":
        tts_type = "ai_qwen"
    elif resolved_provider == "f5":
        tts_type = "ai_f5"
    else:
        tts_type = "ai_unknown"
    return {
        "success": True,
        "queued": True,
        "job_id": job_id,
        "status": state,
        "audio_url": None,
        "selected_voice": None,
        "voice": None,
        "tts_type": tts_type,
        "duration": None,
        "error": None,
        "provider": resolved_provider,
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = get_settings()
    app.state.settings = settings
    app.state.metrics = GatewayMetrics()
    if not settings.api_keys:
        raise RuntimeError("TTS_GATEWAY_API_KEYS must be set (comma-separated API keys)")

    audio_store = AudioStore(settings.audio_path)
    result_ttl_sec = settings.result_timeout_sec + 30
    idempotency_ttl_sec = min(settings.idempotency_ttl_sec, result_ttl_sec)
    if settings.idempotency_ttl_sec > result_ttl_sec:
        logger.warning(
            "TTS_GATEWAY_IDEMPOTENCY_TTL_SEC=%s is higher than result ttl=%s; clamped to %s",
            settings.idempotency_ttl_sec,
            result_ttl_sec,
            idempotency_ttl_sec,
        )
    store = RedisJobStore(
        redis_url=settings.redis_url,
        aging_factor=settings.wfq_aging_factor,
        candidate_window=settings.queue_candidate_window,
        result_ttl_sec=result_ttl_sec,
        idempotency_ttl_sec=idempotency_ttl_sec,
    )
    await store.connect()

    f5_adapter = F5Adapter(
        base_url=settings.f5_url,
        api_key=settings.f5_api_key,
        timeout_sec=settings.request_timeout_sec,
        retry_budget=settings.provider_retry_budget,
        gateway_public_base_url=settings.public_base_url,
        audio_store=audio_store,
    )
    qwen_adapter = QwenAdapter(
        base_url=settings.qwen_url,
        api_key=settings.qwen_api_key,
        timeout_sec=settings.request_timeout_sec,
        retry_budget=settings.provider_retry_budget,
        url_policy=settings.qwen_url_policy,
        gateway_public_base_url=settings.public_base_url,
        audio_store=audio_store,
        max_proxy_audio_bytes=settings.qwen_proxy_max_audio_bytes,
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
    return HealthResponse(**await _runtime_health_payload())


@app.get("/health")
async def health_alias() -> dict[str, str]:
    health = await _runtime_health_payload()
    return {
        "status": "healthy" if health["status"] == "ok" else "degraded",
        "service": "tts-gateway",
        "redis": health["redis"],
        "scheduler": health["scheduler"],
    }


@app.post("/api/tts/synthesize-channel", dependencies=[Depends(verify_api_key)])
async def synthesize_channel(payload: SynthesizeChannelRequest):
    await _require_runtime_ready()
    app.state.metrics.inc_total()
    provider = payload.resolve_provider()
    max_len = max(1, int(app.state.settings.max_input_text_length))
    blocked = {name.strip().lower() for name in payload.blocked_users if name and isinstance(name, str)}
    if payload.author.strip().lower() in blocked:
        app.state.metrics.inc_blocked()
        return {
            "success": False,
            "audio_url": None,
            "voice": None,
            "selected_voice": None,
            "tts_type": "ai_qwen" if provider == "qwen" else "ai_f5",
            "duration": None,
            "error": "Author is blocked",
            "provider": provider,
        }

    text = payload.text
    for word in payload.word_filter:
        if word:
            text = text.replace(word, "")
    text = text.strip()
    if len(text) > max_len:
        return {
            "success": False,
            "audio_url": None,
            "voice": None,
            "selected_voice": None,
            "tts_type": "ai_qwen" if provider == "qwen" else "ai_f5",
            "duration": None,
            "error": f"Text too long. Maximum {max_len} characters",
            "provider": provider,
        }
    if not text:
        app.state.metrics.inc_empty()
        return {
            "success": False,
            "audio_url": None,
            "voice": None,
            "selected_voice": None,
            "tts_type": "ai_qwen" if provider == "qwen" else "ai_f5",
            "duration": None,
            "error": "Text is empty after filtering",
            "provider": provider,
        }

    voice = payload.resolve_voice(provider)
    tenant_id = payload.resolve_tenant()
    idempotency_key = payload.resolve_idempotency_key(provider)
    raw_weight = payload.tts_settings.get("tenant_weight")
    try:
        weight = float(raw_weight if raw_weight is not None else 1.0)
    except Exception:
        weight = 1.0
    if weight <= 0:
        weight = 1.0
    cost = float(max(1, len(text)))

    if idempotency_key:
        existing_job_id = await app.state.store.get_job_id_by_idempotency_key(idempotency_key)
        if existing_job_id:
            app.state.metrics.inc_idempotency_hit()
            if payload.async_mode:
                cached = await app.state.store.get_cached_result(existing_job_id)
                if cached is not None:
                    result_payload = _result_to_payload(cached)
                    result_payload["job_id"] = existing_job_id
                    result_payload["status"] = "done"
                    return result_payload
                state = await app.state.store.get_job_state(existing_job_id)
                return _pending_payload(provider=provider, job_id=existing_job_id, state=state or "queued")
            cached = await app.state.store.wait_result(
                existing_job_id,
                timeout_sec=app.state.settings.result_timeout_sec,
            )
            if cached is None:
                app.state.metrics.inc_timeout()
                raise HTTPException(status_code=504, detail="Gateway timeout waiting provider result")
            app.state.metrics.inc_provider_result(cached.provider, cached.success)
            return _result_to_payload(cached)

    request_payload = payload.model_copy(update={"text": text})
    job_id = uuid.uuid4().hex
    if idempotency_key:
        claimed = await app.state.store.claim_idempotency_key(idempotency_key, job_id)
        if not claimed:
            existing_job_id = await app.state.store.get_job_id_by_idempotency_key(idempotency_key)
            if existing_job_id:
                app.state.metrics.inc_idempotency_hit()
                if payload.async_mode:
                    cached = await app.state.store.get_cached_result(existing_job_id)
                    if cached is not None:
                        result_payload = _result_to_payload(cached)
                        result_payload["job_id"] = existing_job_id
                        result_payload["status"] = "done"
                        return result_payload
                    state = await app.state.store.get_job_state(existing_job_id)
                    return _pending_payload(provider=provider, job_id=existing_job_id, state=state or "queued")
                cached = await app.state.store.wait_result(
                    existing_job_id,
                    timeout_sec=app.state.settings.result_timeout_sec,
                )
                if cached is None:
                    app.state.metrics.inc_timeout()
                    raise HTTPException(status_code=504, detail="Gateway timeout waiting provider result")
                app.state.metrics.inc_provider_result(cached.provider, cached.success)
                return _result_to_payload(cached)

    allowed, current = await app.state.store.check_tenant_rate_limit(
        tenant_id=tenant_id,
        limit_per_minute=app.state.settings.tenant_rate_limit_per_minute,
    )
    if not allowed:
        limit = int(app.state.settings.tenant_rate_limit_per_minute)
        raise HTTPException(
            status_code=429,
            detail=(
                "Rate limit exceeded for tenant "
                f"'{tenant_id}': {limit} requests/minute"
            ),
            headers={
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Current": str(current),
            },
        )

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
    if payload.async_mode:
        return _pending_payload(provider=provider, job_id=job_id, state="queued")

    result = await app.state.store.wait_result(job_id, timeout_sec=app.state.settings.result_timeout_sec)
    if result is None:
        app.state.metrics.inc_timeout()
        raise HTTPException(status_code=504, detail="Gateway timeout waiting provider result")
    app.state.metrics.inc_provider_result(result.provider, result.success)
    return _result_to_payload(result)


@app.get("/api/tts/jobs/{job_id}", dependencies=[Depends(verify_api_key)])
async def get_job_result(job_id: str):
    normalized_job_id = str(job_id or "").strip().lower()
    if not JOB_ID_RE.fullmatch(normalized_job_id):
        raise HTTPException(status_code=400, detail="Invalid job_id")

    cached = await app.state.store.get_cached_result(normalized_job_id)
    if cached is not None:
        payload = _result_to_payload(cached)
        payload["job_id"] = normalized_job_id
        payload["status"] = "done"
        return payload
    state = await app.state.store.get_job_state(normalized_job_id)
    if not state:
        raise HTTPException(status_code=404, detail="Job not found or expired")
    if state == "done":
        raise HTTPException(status_code=410, detail="Job result expired")
    provider = await app.state.store.get_job_provider(normalized_job_id)
    return _pending_payload(provider=provider or "unknown", job_id=normalized_job_id, state=state)


@app.get("/api/admin/stats", dependencies=[Depends(verify_api_key)])
async def admin_stats():
    await _require_runtime_ready()
    queue_depths = await app.state.store.queue_depths()
    job_state_counts = await app.state.store.job_state_counts()
    scheduler = app.state.scheduler.get_runtime_snapshot()
    metrics = app.state.metrics.snapshot()
    return {
        "success": True,
        "queues": queue_depths,
        "jobs": job_state_counts,
        "scheduler": scheduler,
        "metrics": metrics,
    }


@app.get("/api/tts/audio/{filename}")
async def get_audio(filename: str):
    try:
        path = app.state.audio_store.resolve_path(filename)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not path.exists():
        raise HTTPException(status_code=404, detail="Audio not found")
    media_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    return FileResponse(
        path,
        media_type=media_type,
        filename=path.name,
        headers={
            "Cache-Control": "public, max-age=3600",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.get("/")
async def root():
    return {"service": "tts-gateway", "status": "ok"}
