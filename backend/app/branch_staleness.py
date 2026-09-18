from dataclasses import dataclass
from statistics import median


@dataclass(frozen=True)
class BranchStalenessReport:
    active_branches: int
    median_age_days: float
    stale_branches: int
    stale_rate_percent: float
    status: str


def analyze_branch_staleness(
    branch_ages_days: list[float],
    stale_after_days: float = 14.0,
    critical_rate_percent: float = 50.0,
) -> BranchStalenessReport:
    if stale_after_days <= 0:
        raise ValueError("stale_after_days must be positive")
    if not 0 < critical_rate_percent <= 100:
        raise ValueError("critical_rate_percent must be between 0 and 100")
    if any(age < 0 for age in branch_ages_days):
        raise ValueError("branch ages cannot be negative")

    if not branch_ages_days:
        return BranchStalenessReport(0, 0.0, 0, 0.0, "no_data")

    stale = sum(age >= stale_after_days for age in branch_ages_days)
    stale_rate = stale / len(branch_ages_days) * 100.0

    if stale_rate >= critical_rate_percent:
        status = "critical"
    elif stale:
        status = "watch"
    else:
        status = "healthy"

    return BranchStalenessReport(
        active_branches=len(branch_ages_days),
        median_age_days=round(float(median(branch_ages_days)), 2),
        stale_branches=stale,
        stale_rate_percent=round(stale_rate, 2),
        status=status,
    )
