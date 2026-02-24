from __future__ import annotations

import json
import time
from typing import Any

from redis.asyncio import Redis

from .schemas import JobEnvelope, NormalizedSynthesizeResponse


class RedisJobStore:
    def __init__(
        self,
        *,
        redis_url: str,
        aging_factor: float,
        candidate_window: int,
    ) -> None:
        self.redis_url = redis_url
        self.aging_factor = aging_factor
        self.candidate_window = max(1, candidate_window)
        self.redis: Redis | None = None

    async def connect(self) -> None:
        self.redis = Redis.from_url(self.redis_url, decode_responses=True)
        await self.redis.ping()

    async def close(self) -> None:
        if self.redis is not None:
            await self.redis.aclose()
            self.redis = None

    async def ping(self) -> bool:
        if self.redis is None:
            return False
        try:
            await self.redis.ping()
            return True
        except Exception:
            return False

    async def enqueue(self, job: JobEnvelope) -> None:
        redis = self._client()
        now = time.time()
        queue_key = self._provider_queue_key(job.provider)
        vt_key = self._provider_virtual_time_key(job.provider)
        tenant_finish_key = self._provider_tenant_finish_key(job.provider)

        vt_raw = await redis.get(vt_key)
        vt = float(vt_raw) if vt_raw is not None else 0.0
        tenant_last_raw = await redis.hget(tenant_finish_key, job.tenant_id)
        tenant_last = float(tenant_last_raw) if tenant_last_raw is not None else 0.0

        start = max(vt, tenant_last)
        finish = start + (job.cost / job.weight)
        payload = job.model_dump(mode="json")
        payload["wfq_score"] = finish
        payload["enqueued_at"] = now

        pipe = redis.pipeline(transaction=True)
        pipe.set(self._job_key(job.job_id), json.dumps(payload), ex=180)
        pipe.zadd(queue_key, {job.job_id: finish})
        pipe.hset(tenant_finish_key, job.tenant_id, finish)
        pipe.hset(self._job_state_key(), job.job_id, "queued")
        pipe.expire(self._job_state_key(), 180)
        await pipe.execute()

    async def pop_next(self, provider: str) -> JobEnvelope | None:
        redis = self._client()
        queue_key = self._provider_queue_key(provider)
        candidates = await redis.zrange(queue_key, 0, self.candidate_window - 1, withscores=True)
        if not candidates:
            return None

        now = time.time()
        job_ids = [jid for jid, _ in candidates]
        job_json_values = await redis.mget([self._job_key(job_id) for job_id in job_ids])

        best_job_id: str | None = None
        best_base_score: float | None = None
        best_effective = float("inf")
        best_payload_raw: str | None = None

        for (job_id, base_score), payload_raw in zip(candidates, job_json_values, strict=False):
            if not payload_raw:
                continue
            try:
                payload = json.loads(payload_raw)
                created_at = float(payload.get("created_at", now))
            except Exception:
                created_at = now
            age = max(0.0, now - created_at)
            effective = float(base_score) - (self.aging_factor * age)
            if effective < best_effective:
                best_effective = effective
                best_job_id = job_id
                best_base_score = float(base_score)
                best_payload_raw = payload_raw

        if best_job_id is None or best_base_score is None or best_payload_raw is None:
            return None

        removed = await redis.zrem(queue_key, best_job_id)
        if removed != 1:
            return None

        vt_key = self._provider_virtual_time_key(provider)
        vt_raw = await redis.get(vt_key)
        current_vt = float(vt_raw) if vt_raw is not None else 0.0
        if best_base_score > current_vt:
            await redis.set(vt_key, best_base_score, ex=180)

        await redis.hset(self._job_state_key(), best_job_id, "in_progress")
        await redis.expire(self._job_state_key(), 180)
        return JobEnvelope.model_validate(json.loads(best_payload_raw))

    async def publish_result(self, job_id: str, result: NormalizedSynthesizeResponse) -> None:
        redis = self._client()
        raw = result.model_dump_json()
        key = self._result_key(job_id)
        pipe = redis.pipeline(transaction=True)
        pipe.rpush(key, raw)
        pipe.expire(key, 180)
        pipe.hset(self._job_state_key(), job_id, "done")
        pipe.expire(self._job_state_key(), 180)
        await pipe.execute()

    async def wait_result(self, job_id: str, timeout_sec: int) -> NormalizedSynthesizeResponse | None:
        redis = self._client()
        item = await redis.blpop(self._result_key(job_id), timeout=timeout_sec)
        if not item:
            return None
        _, raw = item
        return NormalizedSynthesizeResponse.model_validate(json.loads(raw))

    async def mark_failed(self, job_id: str, provider: str, error: str) -> None:
        await self.publish_result(
            job_id,
            NormalizedSynthesizeResponse(
                success=False,
                audio_url=None,
                selected_voice=None,
                voice=None,
                tts_type="ai_qwen" if provider == "qwen" else "ai_f5",
                duration=None,
                error=error,
                provider="qwen" if provider == "qwen" else "f5",
            ),
        )

    def _client(self) -> Redis:
        if self.redis is None:
            raise RuntimeError("Redis store is not connected")
        return self.redis

    @staticmethod
    def _provider_queue_key(provider: str) -> str:
        return f"ttsgw:queue:{provider}"

    @staticmethod
    def _provider_virtual_time_key(provider: str) -> str:
        return f"ttsgw:wfq:vt:{provider}"

    @staticmethod
    def _provider_tenant_finish_key(provider: str) -> str:
        return f"ttsgw:wfq:last_finish:{provider}"

    @staticmethod
    def _job_key(job_id: str) -> str:
        return f"ttsgw:job:{job_id}"

    @staticmethod
    def _result_key(job_id: str) -> str:
        return f"ttsgw:result:{job_id}"

    @staticmethod
    def _job_state_key() -> str:
        return "ttsgw:job_state"

