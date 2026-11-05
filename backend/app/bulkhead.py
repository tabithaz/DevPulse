from threading import Lock


class InFlightLimiter:
    """Thread-safe, non-blocking capacity guard for outbound collection work."""

    def __init__(self) -> None:
        self._in_flight = 0
        self._rejected_total = 0
        self._lock = Lock()

    @staticmethod
    def _validate_limit(limit: int) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("limit must be a positive integer")

    def try_acquire(self, limit: int) -> bool:
        self._validate_limit(limit)
        with self._lock:
            if self._in_flight >= limit:
                self._rejected_total += 1
                return False
            self._in_flight += 1
            return True

    def release(self) -> None:
        with self._lock:
            self._in_flight = max(0, self._in_flight - 1)

    def snapshot(self, limit: int) -> dict[str, int]:
        self._validate_limit(limit)
        with self._lock:
            return {
                "limit": limit,
                "in_flight": self._in_flight,
                "rejected_total": self._rejected_total,
            }
