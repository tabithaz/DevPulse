from dataclasses import dataclass
from statistics import median


@dataclass(frozen=True)
class WorkInProgressReport:
    open_changes: int
    median_age_hours: float
    aging_changes: int
    aging_rate_percent: float
    status: str


def analyze_work_in_progress(
    change_ages_hours: list[float],
    aging_hours: float = 48.0,
    critical_rate_percent: float = 40.0,
) -> WorkInProgressReport:
    if aging_hours <= 0:
        raise ValueError("aging_hours must be positive")
    if not 0 < critical_rate_percent <= 100:
        raise ValueError("critical_rate_percent must be between 0 and 100")
    if any(isinstance(age, bool) or not isinstance(age, (int, float)) or age < 0 for age in change_ages_hours):
        raise ValueError("change ages must be non-negative numbers")
    if not change_ages_hours:
        return WorkInProgressReport(0, 0.0, 0, 0.0, "no_data")

    aging = sum(age >= aging_hours for age in change_ages_hours)
    rate = aging / len(change_ages_hours) * 100.0
    if rate >= critical_rate_percent:
        status = "congested"
    elif aging:
        status = "watch"
    else:
        status = "healthy"

    return WorkInProgressReport(
        open_changes=len(change_ages_hours),
        median_age_hours=round(float(median(change_ages_hours)), 2),
        aging_changes=aging,
        aging_rate_percent=round(rate, 2),
        status=status,
    )
