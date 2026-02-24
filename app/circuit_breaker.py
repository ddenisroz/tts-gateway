from __future__ import annotations

from dataclasses import dataclass
from time import time


@dataclass
class CircuitBreaker:
    failure_threshold: int
    recovery_timeout_sec: float
    failures: int = 0
    opened_at: float | None = None

    def is_open(self) -> bool:
        if self.opened_at is None:
            return False
        if (time() - self.opened_at) >= self.recovery_timeout_sec:
            self.opened_at = None
            self.failures = 0
            return False
        return True

    def record_success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.failure_threshold:
            self.opened_at = time()

