from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class ReviewLatencyReport:
    reviewed_pull_requests: int
    median_first_review_hours: float
    p90_first_review_hours: float
    overdue_reviews: int
    overdue_rate_percent: float
    status: str


def _is_finite_number(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return isfinite(value)
    except OverflowError:
        return False


def analyze_review_latency(
    first_review_hours: list[float],
    target_hours: float = 24.0,
    critical_overdue_percent: float = 40.0,
) -> ReviewLatencyReport:
    if not _is_finite_number(target_hours) or target_hours <= 0:
        raise ValueError("target_hours must be a finite positive number")
    if not _is_finite_number(critical_overdue_percent) or not 0 < critical_overdue_percent <= 100:
        raise ValueError("critical_overdue_percent must be finite and between 0 and 100")
    if any(not _is_finite_number(hours) or hours < 0 for hours in first_review_hours):
        raise ValueError("review latency must be a finite nonnegative number")
    if not first_review_hours:
        return ReviewLatencyReport(0, 0.0, 0.0, 0, 0.0, "no_data")

    ordered = sorted(first_review_hours)
    p90_index = max(0, (9 * len(ordered) + 9) // 10 - 1)
    overdue = sum(hours > target_hours for hours in ordered)
    overdue_rate = overdue / len(ordered) * 100.0

    if overdue_rate >= critical_overdue_percent:
        status = "critical"
    elif overdue:
        status = "watch"
    else:
        status = "healthy"

    middle = len(ordered) // 2
    if len(ordered) % 2:
        median_hours = float(ordered[middle])
    else:
        lower = float(ordered[middle - 1])
        upper = float(ordered[middle])
        median_hours = lower + (upper - lower) / 2.0

    return ReviewLatencyReport(
        reviewed_pull_requests=len(ordered),
        median_first_review_hours=round(median_hours, 2),
        p90_first_review_hours=round(float(ordered[p90_index]), 2),
        overdue_reviews=overdue,
        overdue_rate_percent=round(overdue_rate, 2),
        status=status,
    )
