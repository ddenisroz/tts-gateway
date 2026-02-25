from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from time import time

from .adapters.base import ProviderAdapter
from .circuit_breaker import CircuitBreaker
from .redis_store import RedisJobStore
from .schemas import JobEnvelope, NormalizedSynthesizeResponse

logger = logging.getLogger(__name__)


class Scheduler:
    def __init__(
        self,
        *,
        store: RedisJobStore,
        adapters: Mapping[str, ProviderAdapter],
        lane_limits: Mapping[str, int],
        poll_ms: int,
        circuit_failure_threshold: int,
        circuit_recovery_sec: float,
    ) -> None:
        self.store = store
        self.adapters = dict(adapters)
        self.lane_limits = {provider: max(1, int(limit)) for provider, limit in lane_limits.items()}
        self.poll_ms = max(1, int(poll_ms))
        self.circuits = {
            provider: CircuitBreaker(
                failure_threshold=max(1, circuit_failure_threshold),
                recovery_timeout_sec=max(1.0, circuit_recovery_sec),
            )
            for provider in self.adapters.keys()
        }
        self.in_flight = {provider: 0 for provider in self.adapters.keys()}
        self._lock = asyncio.Lock()
        self._loop_task: asyncio.Task | None = None
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._loop_task = asyncio.create_task(self._run_loop(), name="tts-gateway-scheduler")

    async def stop(self) -> None:
        self._running = False
        if self._loop_task is not None:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
            self._loop_task = None

    async def _run_loop(self) -> None:
        providers = list(self.adapters.keys())
        while self._running:
            for provider in providers:
                if not self._running:
                    break
                if self.circuits[provider].is_open():
                    continue
                if self.in_flight[provider] >= self.lane_limits[provider]:
                    continue
                job = await self.store.pop_next(provider)
                if job is None:
                    continue
                await self._dispatch(job)
            await asyncio.sleep(self.poll_ms / 1000.0)

    async def _dispatch(self, job: JobEnvelope) -> None:
        provider = job.provider
        async with self._lock:
            if self.in_flight[provider] >= self.lane_limits[provider]:
                # If lane got busy in a race, requeue job at the same cost/tenant.
                await self.store.enqueue(job)
                return
            self.in_flight[provider] += 1
        asyncio.create_task(self._execute(job), name=f"tts-job-{job.job_id}")

    async def _execute(self, job: JobEnvelope) -> None:
        provider = job.provider
        adapter = self.adapters[provider]
        circuit = self.circuits[provider]
        try:
            if circuit.is_open():
                await self.store.mark_failed(job.job_id, provider, "provider circuit open")
                return
            result = await adapter.synthesize(job)
            if result.success:
                circuit.record_success()
            else:
                circuit.record_failure()
            await self.store.publish_result(job.job_id, result)
        except Exception as error:
            logger.exception("Scheduler job failed provider=%s job_id=%s", provider, job.job_id)
            circuit.record_failure()
            await self.store.publish_result(
                job.job_id,
                NormalizedSynthesizeResponse(
                    success=False,
                    audio_url=None,
                    selected_voice=job.voice,
                    voice=job.voice,
                    tts_type="ai_qwen" if provider == "qwen" else "ai_f5",
                    duration=None,
                    error=str(error),
                    provider=provider,  # type: ignore[arg-type]
                ),
            )
        finally:
            async with self._lock:
                self.in_flight[provider] = max(0, self.in_flight[provider] - 1)

    def get_runtime_snapshot(self) -> dict[str, object]:
        now = time()
        circuits: dict[str, dict[str, object]] = {}
        for provider, circuit in self.circuits.items():
            opened = circuit.is_open()
            opened_for = 0.0
            if circuit.opened_at is not None:
                opened_for = max(0.0, now - circuit.opened_at)
            circuits[provider] = {
                "is_open": opened,
                "failures": circuit.failures,
                "opened_for_sec": round(opened_for, 3),
            }
        return {
            "running": self.running,
            "in_flight": dict(self.in_flight),
            "lane_limits": dict(self.lane_limits),
            "circuits": circuits,
        }
