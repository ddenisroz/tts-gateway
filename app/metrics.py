from __future__ import annotations

from collections import defaultdict
from threading import Lock
from typing import Any


class GatewayMetrics:
    def __init__(self) -> None:
        self._lock = Lock()
        self._total_requests = 0
        self._blocked_requests = 0
        self._empty_requests = 0
        self._timeouts = 0
        self._idempotency_hits = 0
        self._provider_success: dict[str, int] = defaultdict(int)
        self._provider_failure: dict[str, int] = defaultdict(int)

    def inc_total(self) -> None:
        with self._lock:
            self._total_requests += 1

    def inc_blocked(self) -> None:
        with self._lock:
            self._blocked_requests += 1

    def inc_empty(self) -> None:
        with self._lock:
            self._empty_requests += 1

    def inc_timeout(self) -> None:
        with self._lock:
            self._timeouts += 1

    def inc_idempotency_hit(self) -> None:
        with self._lock:
            self._idempotency_hits += 1

    def inc_provider_result(self, provider: str, success: bool) -> None:
        key = str(provider or "unknown").strip().lower() or "unknown"
        with self._lock:
            if success:
                self._provider_success[key] += 1
            else:
                self._provider_failure[key] += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "total_requests": self._total_requests,
                "blocked_requests": self._blocked_requests,
                "empty_requests": self._empty_requests,
                "timeouts": self._timeouts,
                "idempotency_hits": self._idempotency_hits,
                "provider_success": dict(self._provider_success),
                "provider_failure": dict(self._provider_failure),
            }
