from collections import defaultdict
from threading import Lock


REQUEST_DURATION_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)


class RequestMetrics:
    """Thread-safe HTTP RED metrics with bounded route labels."""

    def __init__(self) -> None:
        self._requests: dict[tuple[str, str, int], int] = defaultdict(int)
        self._duration_count: dict[tuple[str, str], int] = defaultdict(int)
        self._duration_sum: dict[tuple[str, str], float] = defaultdict(float)
        self._duration_buckets: dict[tuple[str, str], list[int]] = {}
        self._in_flight = 0
        self._lock = Lock()

    def begin(self) -> None:
        with self._lock:
            self._in_flight += 1

    def observe(
        self,
        method: str,
        route: str,
        status_code: int,
        duration_seconds: float,
    ) -> None:
        key = (method, route)
        with self._lock:
            self._requests[(method, route, status_code)] += 1
            self._duration_count[key] += 1
            self._duration_sum[key] += duration_seconds
            buckets = self._duration_buckets.setdefault(
                key,
                [0 for _ in REQUEST_DURATION_BUCKETS],
            )
            for index, boundary in enumerate(REQUEST_DURATION_BUCKETS):
                if duration_seconds <= boundary:
                    buckets[index] += 1
            self._in_flight = max(0, self._in_flight - 1)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "in_flight": self._in_flight,
                "requests": dict(self._requests),
                "duration_count": dict(self._duration_count),
                "duration_sum": dict(self._duration_sum),
                "duration_buckets": {
                    key: list(counts)
                    for key, counts in self._duration_buckets.items()
                },
            }


def _label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def render_request_metrics(snapshot: dict) -> list[str]:
    lines = [
        "# HELP devpulse_http_requests_total Completed HTTP requests by route and status.",
        "# TYPE devpulse_http_requests_total counter",
    ]
    for (method, route, status), count in sorted(snapshot["requests"].items()):
        lines.append(
            "devpulse_http_requests_total"
            f'{{method="{_label(method)}",route="{_label(route)}",status="{status}"}} {count}'
        )
    lines.extend((
        "# HELP devpulse_http_request_duration_seconds HTTP request latency by route.",
        "# TYPE devpulse_http_request_duration_seconds histogram",
    ))
    for (method, route), count in sorted(snapshot["duration_count"].items()):
        labels = f'method="{_label(method)}",route="{_label(route)}"'
        for boundary, bucket_count in zip(
            REQUEST_DURATION_BUCKETS,
            snapshot["duration_buckets"][(method, route)],
        ):
            lines.append(
                "devpulse_http_request_duration_seconds_bucket"
                f'{{{labels},le="{boundary:g}"}} {bucket_count}'
            )
        lines.extend((
            "devpulse_http_request_duration_seconds_bucket"
            f'{{{labels},le="+Inf"}} {count}',
            "devpulse_http_request_duration_seconds_sum"
            f'{{{labels}}} {snapshot["duration_sum"][(method, route)]:.15g}',
            "devpulse_http_request_duration_seconds_count"
            f'{{{labels}}} {count}',
        ))
    lines.extend((
        "# HELP devpulse_http_requests_in_flight HTTP requests currently executing.",
        "# TYPE devpulse_http_requests_in_flight gauge",
        f'devpulse_http_requests_in_flight {snapshot["in_flight"]}',
    ))
    return lines
