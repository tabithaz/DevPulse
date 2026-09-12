from statistics import mean, pstdev


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
        "status": status,
    }
