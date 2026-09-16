from dataclasses import dataclass
from statistics import median


@dataclass(frozen=True)
class MergeQueueReport:
    queued_changes: int
    median_wait_minutes: float
    oldest_wait_minutes: float
    stale_changes: int
    status: str


def analyze_merge_queue(
    wait_minutes: list[float],
    warning_minutes: float = 30.0,
    critical_minutes: float = 90.0,
) -> MergeQueueReport:
    if warning_minutes <= 0 or critical_minutes <= warning_minutes:
        raise ValueError("thresholds must satisfy 0 < warning < critical")
    if any(wait < 0 for wait in wait_minutes):
        raise ValueError("queue wait times cannot be negative")
    if not wait_minutes:
        return MergeQueueReport(0, 0.0, 0.0, 0, "empty")

    oldest = max(wait_minutes)
    stale = sum(wait >= warning_minutes for wait in wait_minutes)
    stale_rate = stale / len(wait_minutes)

    if oldest >= critical_minutes or stale_rate >= 0.5:
        status = "congested"
    elif stale:
        status = "watch"
    else:
        status = "healthy"

    return MergeQueueReport(
        queued_changes=len(wait_minutes),
        median_wait_minutes=round(float(median(wait_minutes)), 2),
        oldest_wait_minutes=round(float(oldest), 2),
        stale_changes=stale,
        status=status,
    )
