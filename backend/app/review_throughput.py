from dataclasses import dataclass
from statistics import median


@dataclass(frozen=True)
class ReviewThroughputReport:
    days: int
    total_reviews: int
    median_reviews_per_day: float
    active_day_rate_percent: float
    peak_reviews: int
    status: str


def analyze_review_throughput(daily_reviews: list[int], minimum_active_rate_percent: float = 60.0) -> ReviewThroughputReport:
    if not 0 <= minimum_active_rate_percent <= 100:
        raise ValueError("minimum_active_rate_percent must be between 0 and 100")
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in daily_reviews):
        raise ValueError("daily review counts must be non-negative integers")
    if not daily_reviews:
        return ReviewThroughputReport(0, 0, 0.0, 0.0, 0, "no_data")

    active_days = sum(value > 0 for value in daily_reviews)
    active_rate = active_days / len(daily_reviews) * 100.0
    if active_rate >= minimum_active_rate_percent:
        status = "steady"
    elif active_days:
        status = "intermittent"
    else:
        status = "idle"

    return ReviewThroughputReport(
        days=len(daily_reviews),
        total_reviews=sum(daily_reviews),
        median_reviews_per_day=round(float(median(daily_reviews)), 2),
        active_day_rate_percent=round(active_rate, 2),
        peak_reviews=max(daily_reviews),
        status=status,
    )
