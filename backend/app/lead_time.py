from dataclasses import dataclass
from statistics import median


@dataclass(frozen=True)
class LeadTimeReport:
    count: int
    median_hours: float
    p90_hours: float
    slow_changes: int
    slow_change_rate_percent: float
    status: str


def analyze_lead_time(
    lead_times_hours: list[float],
    warning_hours: float = 48.0,
    critical_hours: float = 120.0,
) -> LeadTimeReport:
    if warning_hours <= 0 or critical_hours <= warning_hours:
        raise ValueError("thresholds must satisfy 0 < warning < critical")
    if any(value < 0 for value in lead_times_hours):
        raise ValueError("lead times cannot be negative")
    if not lead_times_hours:
        return LeadTimeReport(0, 0.0, 0.0, 0, 0.0, "no_data")

    ordered = sorted(lead_times_hours)
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
        median_hours=round(float(median(ordered)), 2),
        p90_hours=round(float(p90), 2),
        slow_changes=slow_changes,
        slow_change_rate_percent=round(slow_rate, 2),
        status=status,
    )
