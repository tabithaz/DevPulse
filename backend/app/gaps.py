def analyze_activity_gaps(daily_events):
    if not isinstance(daily_events, list) or any(not isinstance(v, int) or v < 0 for v in daily_events):
        raise ValueError("daily_events must be a list of non-negative integers")

    longest_gap = 0
    current_gap = 0
    gap_count = 0
    completed_gaps = []
    in_gap = False
    recovery_events = 0

    for events in daily_events:
        if events == 0:
            current_gap += 1
            longest_gap = max(longest_gap, current_gap)
            if not in_gap:
                gap_count += 1
                in_gap = True
        else:
            if in_gap:
                completed_gaps.append(current_gap)
                recovery_events += events
            current_gap = 0
            in_gap = False

    if in_gap:
        completed_gaps.append(current_gap)

    total_days = len(daily_events)
    inactive_days = sum(1 for value in daily_events if value == 0)
    inactivity_rate = round((inactive_days / total_days) * 100, 1) if total_days else 0.0
    average_gap_days = round(inactive_days / gap_count, 1) if gap_count else 0.0
    sorted_gaps = sorted(completed_gaps)
    midpoint = len(sorted_gaps) // 2
    if not sorted_gaps:
        median_gap_days = 0.0
    elif len(sorted_gaps) % 2:
        median_gap_days = float(sorted_gaps[midpoint])
    else:
        median_gap_days = round((sorted_gaps[midpoint - 1] + sorted_gaps[midpoint]) / 2, 1)

    if inactivity_rate >= 60 or longest_gap >= 5:
        status = "at_risk"
    elif inactivity_rate >= 30 or longest_gap >= 3:
        status = "inconsistent"
    else:
        status = "consistent"

    return {
        "days_observed": total_days,
        "inactive_days": inactive_days,
        "inactivity_rate": inactivity_rate,
        "gap_count": gap_count,
        "longest_gap_days": longest_gap,
        "current_gap_days": current_gap,
        "average_gap_days": average_gap_days,
        "median_gap_days": median_gap_days,
        "recovery_events": recovery_events,
        "status": status,
    }
