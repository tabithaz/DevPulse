from statistics import mean, pstdev


def _longest_inactive_streak(daily_events: list[int]) -> int:
    longest = 0
    current = 0
    for value in daily_events:
        if value == 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def analyze_activity_volatility(daily_events: list[int]) -> dict:
    if not isinstance(daily_events, list) or not daily_events:
        raise ValueError("daily_events must be a non-empty list")
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in daily_events):
        raise ValueError("daily_events must contain non-negative integers")

    avg = mean(daily_events)
    deviation = pstdev(daily_events)
    coefficient = 0.0 if avg == 0 else deviation / avg

    if avg == 0:
        status = "inactive"
    elif coefficient < 0.35:
        status = "stable"
    elif coefficient < 0.75:
        status = "variable"
    else:
        status = "volatile"

    return {
        "average_daily_events": round(avg, 2),
        "standard_deviation": round(deviation, 2),
        "coefficient_of_variation": round(coefficient, 3),
        "peak_to_average_ratio": round(max(daily_events) / avg, 2) if avg else 0.0,
        "longest_inactive_streak_days": _longest_inactive_streak(daily_events),
        "status": status,
    }
