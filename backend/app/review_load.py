from dataclasses import dataclass


@dataclass(frozen=True)
class ReviewLoadReport:
    reviewer_count: int
    total_reviews: int
    busiest_reviewer_share_percent: float
    load_imbalance_ratio: float
    status: str


def analyze_review_load(review_counts: dict[str, int]) -> ReviewLoadReport:
    """Measure how evenly pull-request reviews are distributed across reviewers."""
    if any(not name.strip() for name in review_counts):
        raise ValueError("reviewer names must not be blank")
    if any(count < 0 for count in review_counts.values()):
        raise ValueError("review counts cannot be negative")

    active_counts = [count for count in review_counts.values() if count > 0]
    total = sum(active_counts)
    if total == 0:
        return ReviewLoadReport(0, 0, 0.0, 0.0, "no_data")

    busiest = max(active_counts)
    average = total / len(active_counts)
    busiest_share = busiest / total * 100.0
    imbalance = busiest / average

    if busiest_share >= 70.0 or imbalance >= 2.5:
        status = "concentrated"
    elif busiest_share >= 50.0 or imbalance >= 1.75:
        status = "watch"
    else:
        status = "balanced"

    return ReviewLoadReport(
        reviewer_count=len(active_counts),
        total_reviews=total,
        busiest_reviewer_share_percent=round(busiest_share, 2),
        load_imbalance_ratio=round(imbalance, 2),
        status=status,
    )
