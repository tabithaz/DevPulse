from dataclasses import dataclass
from statistics import mean

@dataclass(frozen=True)
class ReviewerLoadReport:
    reviewers: int
    total_reviews: int
    average_reviews: float
    busiest_reviewer_reviews: int
    imbalance_ratio: float
    status: str

def analyze_reviewer_load(review_counts, warning_ratio=2.0, critical_ratio=3.0):
    if warning_ratio <= 1 or critical_ratio <= warning_ratio:
        raise ValueError("thresholds must satisfy 1 < warning < critical")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0 for v in review_counts):
        raise ValueError("review counts must be non-negative numbers")
    if not review_counts:
        return ReviewerLoadReport(0, 0, 0.0, 0, 0.0, "no_data")
    average = mean(review_counts)
    busiest = max(review_counts)
    ratio = busiest / average if average else 0.0
    status = "critical" if ratio >= critical_ratio else "watch" if ratio >= warning_ratio else "balanced"
    return ReviewerLoadReport(len(review_counts), int(sum(review_counts)), round(average, 2), int(busiest), round(ratio, 2), status)
