from dataclasses import dataclass
from statistics import median


@dataclass(frozen=True)
class ReviewCycleSummary:
    pull_requests: int
    median_hours_to_first_review: float
    p90_hours_to_first_review: float
    sla_breaches: int
    sla_breach_rate: float
    status: str


def analyze_review_cycle(review_hours: list[float], sla_hours: float = 24.0) -> ReviewCycleSummary:
    if sla_hours <= 0:
        raise ValueError("sla_hours must be positive")
    if any(hours < 0 for hours in review_hours):
        raise ValueError("review times cannot be negative")
    if not review_hours:
        return ReviewCycleSummary(0, 0.0, 0.0, 0, 0.0, "no_data")

    ordered = sorted(review_hours)
    percentile_index = max(0, int((len(ordered) - 1) * 0.9 + 0.999999))
    p90 = ordered[percentile_index]
    breaches = sum(hours > sla_hours for hours in ordered)
    breach_rate = breaches / len(ordered)

    if breach_rate >= 0.4 or p90 > sla_hours * 2:
        status = "slow"
    elif breach_rate > 0 or p90 > sla_hours:
        status = "watch"
    else:
        status = "healthy"

    return ReviewCycleSummary(
        pull_requests=len(ordered),
        median_hours_to_first_review=round(float(median(ordered)), 2),
        p90_hours_to_first_review=round(float(p90), 2),
        sla_breaches=breaches,
        sla_breach_rate=round(breach_rate, 4),
        status=status,
    )
