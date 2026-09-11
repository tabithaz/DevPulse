from dataclasses import dataclass


@dataclass(frozen=True)
class ActivityForecast:
    forecast_events: int
    momentum_percent: float
    confidence: str


def forecast_activity(recent_windows: list[int]) -> ActivityForecast:
    """Forecast the next activity window using a recency-weighted average."""
    if not recent_windows:
        raise ValueError("at least one activity window is required")
    if any(events < 0 for events in recent_windows):
        raise ValueError("event counts must be non-negative")

    weights = list(range(1, len(recent_windows) + 1))
    weighted_total = sum(events * weight for events, weight in zip(recent_windows, weights))
    forecast_events = round(weighted_total / sum(weights))

    if len(recent_windows) == 1 or recent_windows[-2] == 0:
        momentum_percent = 0.0 if recent_windows[-1] == 0 else 100.0
    else:
        momentum_percent = round(
            ((recent_windows[-1] - recent_windows[-2]) / recent_windows[-2]) * 100.0,
            1,
        )

    if len(recent_windows) >= 4:
        confidence = "high"
    elif len(recent_windows) >= 2:
        confidence = "medium"
    else:
        confidence = "low"

    return ActivityForecast(
        forecast_events=forecast_events,
        momentum_percent=momentum_percent,
        confidence=confidence,
    )
