from dataclasses import dataclass
from statistics import median


@dataclass(frozen=True)
class ReviewLatencyReport:
    reviewed_pull_requests: int
    median_first_review_hours: float
    p90_first_review_hours: float
    overdue_reviews: int
    overdue_rate_percent: float
    status: str


def analyze_review_latency(
    first_review_hours: list[float],
    target_hours: float = 24.0,
    critical_overdue_percent: float = 40.0,
) -> ReviewLatencyReport:
    if target_hours <= 0:
        raise ValueError("target_hours must be positive")
    if not 0 < critical_overdue_percent <= 100:
        raise ValueError("critical_overdue_percent must be between 0 and 100")
    if any(hours < 0 for hours in first_review_hours):
        raise ValueError("review latency cannot be negative")
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

    return ReviewLatencyReport(
        reviewed_pull_requests=len(ordered),
        median_first_review_hours=round(float(median(ordered)), 2),
        p90_first_review_hours=round(float(ordered[p90_index]), 2),
        overdue_reviews=overdue,
        overdue_rate_percent=round(overdue_rate, 2),
        status=status,
    )
