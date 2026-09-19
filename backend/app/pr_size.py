from dataclasses import dataclass
from statistics import median


@dataclass(frozen=True)
class PullRequestSizeReport:
    pull_requests: int
    median_changed_lines: float
    largest_changed_lines: int
    oversized_pull_requests: int
    oversized_rate_percent: float
    status: str


def analyze_pull_request_sizes(
    changed_lines: list[int],
    warning_lines: int = 400,
    critical_lines: int = 1000,
) -> PullRequestSizeReport:
    if warning_lines <= 0 or critical_lines <= warning_lines:
        raise ValueError("size thresholds must be positive and increasing")
    if any(isinstance(lines, bool) or not isinstance(lines, int) or lines < 0 for lines in changed_lines):
        raise ValueError("changed line counts must be non-negative integers")

    if not changed_lines:
        return PullRequestSizeReport(0, 0.0, 0, 0, 0.0, "no_data")

    oversized = sum(lines >= warning_lines for lines in changed_lines)
    critical = sum(lines >= critical_lines for lines in changed_lines)
    oversized_rate = oversized / len(changed_lines) * 100.0

    if critical > 0 or oversized_rate >= 50.0:
        status = "high_risk"
    elif oversized > 0:
        status = "watch"
    else:
        status = "healthy"

    return PullRequestSizeReport(
        pull_requests=len(changed_lines),
        median_changed_lines=round(float(median(changed_lines)), 1),
        largest_changed_lines=max(changed_lines),
        oversized_pull_requests=oversized,
        oversized_rate_percent=round(oversized_rate, 1),
        status=status,
    )
