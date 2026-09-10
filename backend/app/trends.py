from dataclasses import dataclass


@dataclass(frozen=True)
class TrendResult:
    direction: str
    percent_change: float
    delta: int


def analyze_activity_trend(previous_events: int, current_events: int) -> TrendResult:
    """Compare two activity windows without producing unstable percentages."""
    if previous_events < 0 or current_events < 0:
        raise ValueError("event counts must be non-negative")

    delta = current_events - previous_events
    if delta > 0:
        direction = "increasing"
    elif delta < 0:
        direction = "decreasing"
    else:
        direction = "steady"

    if previous_events == 0:
        percent_change = 0.0 if current_events == 0 else 100.0
    else:
        percent_change = round((delta / previous_events) * 100.0, 1)

    return TrendResult(
        direction=direction,
        percent_change=percent_change,
        delta=delta,
    )
