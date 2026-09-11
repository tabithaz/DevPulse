from collections.abc import Sequence


def analyze_contribution_streak(daily_events: Sequence[int]) -> dict:
    """Summarize contribution consistency from oldest to newest daily event counts."""
    if any(count < 0 for count in daily_events):
        raise ValueError("daily event counts must be non-negative")

    active_days = sum(1 for count in daily_events if count > 0)
    total_days = len(daily_events)

    longest_streak = 0
    running_streak = 0
    for count in daily_events:
        if count > 0:
            running_streak += 1
            longest_streak = max(longest_streak, running_streak)
        else:
            running_streak = 0

    current_streak = 0
    for count in reversed(daily_events):
        if count == 0:
            break
        current_streak += 1

    return {
        "days_observed": total_days,
        "active_days": active_days,
        "current_streak": current_streak,
        "longest_streak": longest_streak,
        "consistency_percent": round((active_days / total_days) * 100, 1)
        if total_days
        else 0.0,
    }
