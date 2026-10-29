from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class LeadTimeReport:
    count: int
    median_hours: float
    p90_hours: float
    slow_changes: int
    slow_change_rate_percent: float
    status: str


def _is_finite_number(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return isfinite(value)
    except OverflowError:
        return False


def analyze_lead_time(
    lead_times_hours: list[float],
    warning_hours: float = 48.0,
    critical_hours: float = 120.0,
) -> LeadTimeReport:
    if (
        not _is_finite_number(warning_hours)
        or not _is_finite_number(critical_hours)
        or warning_hours <= 0
        or critical_hours <= warning_hours
    ):
        raise ValueError("thresholds must be finite and satisfy 0 < warning < critical")
    if any(not _is_finite_number(value) or value < 0 for value in lead_times_hours):
        raise ValueError("lead times must be finite, non-negative numbers")
    if not lead_times_hours:
        return LeadTimeReport(0, 0.0, 0.0, 0, 0.0, "no_data")

    ordered = sorted(lead_times_hours)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        median_hours = float(ordered[midpoint])
    else:
        lower = float(ordered[midpoint - 1])
        upper = float(ordered[midpoint])
        median_hours = lower + (upper - lower) / 2

    p90_index = max(0, min(len(ordered) - 1, (9 * len(ordered) + 9) // 10 - 1))
    p90 = ordered[p90_index]
    slow_changes = sum(value >= warning_hours for value in ordered)
    slow_rate = slow_changes / len(ordered) * 100.0

    if p90 >= critical_hours or slow_rate >= 50.0:
        status = "critical"
    elif p90 >= warning_hours or slow_changes > 0:
        status = "watch"
    else:
        status = "healthy"

    return LeadTimeReport(
        count=len(ordered),
        median_hours=round(median_hours, 2),
        p90_hours=round(float(p90), 2),
        slow_changes=slow_changes,
        slow_change_rate_percent=round(slow_rate, 2),
        status=status,
    )
