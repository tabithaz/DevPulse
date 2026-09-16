from dataclasses import dataclass


@dataclass(frozen=True)
class ReworkReport:
    pull_requests: int
    total_review_rounds: int
    average_review_rounds: float
    reworked_pull_requests: int
    rework_rate_percent: float
    status: str


def analyze_rework(
    review_rounds: list[int],
    warning_percent: float = 25.0,
    critical_percent: float = 50.0,
) -> ReworkReport:
    """Measure how often pull requests require multiple review rounds."""
    if warning_percent < 0 or critical_percent <= warning_percent:
        raise ValueError("thresholds must satisfy 0 <= warning < critical")
    if any(rounds < 1 for rounds in review_rounds):
        raise ValueError("each pull request must have at least one review round")

    pull_requests = len(review_rounds)
    if pull_requests == 0:
        return ReworkReport(0, 0, 0.0, 0, 0.0, "no_data")

    total_rounds = sum(review_rounds)
    reworked = sum(rounds > 1 for rounds in review_rounds)
    rework_rate = reworked / pull_requests * 100.0

    if rework_rate < warning_percent:
        status = "healthy"
    elif rework_rate < critical_percent:
        status = "watch"
    else:
        status = "high_rework"

    return ReworkReport(
        pull_requests=pull_requests,
        total_review_rounds=total_rounds,
        average_review_rounds=round(total_rounds / pull_requests, 2),
        reworked_pull_requests=reworked,
        rework_rate_percent=round(rework_rate, 2),
        status=status,
    )
