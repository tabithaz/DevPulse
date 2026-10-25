from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class QueueTailReport:
    queued_changes: int
    p95_wait_minutes: float
    over_warning: int
    over_critical: int
    status: str


def _is_finite_number(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return isfinite(value)
    except OverflowError:
        return False


def analyze_queue_tail(
    wait_minutes: list[float],
    warning_minutes: float = 45.0,
    critical_minutes: float = 120.0,
) -> QueueTailReport:
    if (
        not _is_finite_number(warning_minutes)
        or not _is_finite_number(critical_minutes)
        or warning_minutes <= 0
        or critical_minutes <= warning_minutes
    ):
        raise ValueError("thresholds must be finite and satisfy 0 < warning < critical")
    if any(not _is_finite_number(wait) or wait < 0 for wait in wait_minutes):
        raise ValueError("queue wait times must be finite, nonnegative numbers")
    if not wait_minutes:
        return QueueTailReport(0, 0.0, 0, 0, "no_data")

    ordered = sorted(wait_minutes)
    p95_index = (95 * len(ordered) + 99) // 100 - 1
    p95 = ordered[p95_index]
    over_warning = sum(wait >= warning_minutes for wait in ordered)
    over_critical = sum(wait >= critical_minutes for wait in ordered)

    if p95 >= critical_minutes:
        status = "critical"
    elif p95 >= warning_minutes:
        status = "watch"
    else:
        status = "healthy"

    return QueueTailReport(
        queued_changes=len(ordered),
        p95_wait_minutes=round(float(p95), 2),
        over_warning=over_warning,
        over_critical=over_critical,
        status=status,
    )
