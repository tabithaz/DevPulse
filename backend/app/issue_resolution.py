from dataclasses import dataclass
from statistics import median


@dataclass(frozen=True)
class IssueResolutionReport:
    resolved_issues: int
    median_resolution_hours: float
    p90_resolution_hours: float
    sla_breach_rate_percent: float
    status: str


def analyze_issue_resolution(
    resolution_hours: list[float],
    sla_hours: float = 72.0,
) -> IssueResolutionReport:
    if sla_hours <= 0:
        raise ValueError("sla_hours must be greater than zero")
    if any(hours < 0 for hours in resolution_hours):
        raise ValueError("resolution hours cannot be negative")

    if not resolution_hours:
        return IssueResolutionReport(0, 0.0, 0.0, 0.0, "no_data")

    ordered = sorted(resolution_hours)
    p90_index = max(0, int(len(ordered) * 0.9 + 0.999999) - 1)
    breaches = sum(hours > sla_hours for hours in ordered)
    breach_rate = breaches / len(ordered) * 100.0

    if breach_rate < 10.0:
        status = "healthy"
    elif breach_rate < 30.0:
        status = "watch"
    else:
        status = "slow"

    return IssueResolutionReport(
        resolved_issues=len(ordered),
        median_resolution_hours=round(float(median(ordered)), 2),
        p90_resolution_hours=round(float(ordered[p90_index]), 2),
        sla_breach_rate_percent=round(breach_rate, 2),
        status=status,
    )
