from statistics import mean, pstdev


def analyze_cadence(daily_events: list[int]) -> dict:
    """Measure how consistently development activity is distributed across days."""
    if not daily_events:
        raise ValueError("daily_events must contain at least one day")
    if any((not isinstance(value, int)) or value < 0 for value in daily_events):
        raise ValueError("daily_events must contain non-negative integers")

    average = mean(daily_events)
    deviation = pstdev(daily_events)
    active_days = sum(value > 0 for value in daily_events)
    active_ratio = active_days / len(daily_events)

    if average == 0:
        coefficient_of_variation = 0.0
        stability = "inactive"
    else:
        coefficient_of_variation = deviation / average
        if active_ratio >= 0.8 and coefficient_of_variation <= 0.5:
            stability = "steady"
        elif active_ratio >= 0.5 and coefficient_of_variation <= 1.0:
            stability = "variable"
        else:
            stability = "bursty"

    return {
        "days_observed": len(daily_events),
        "active_days": active_days,
        "active_day_percentage": round(active_ratio * 100, 1),
        "average_events_per_day": round(average, 2),
        "event_std_dev": round(deviation, 2),
        "coefficient_of_variation": round(coefficient_of_variation, 3),
        "stability": stability,
    }
