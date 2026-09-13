from __future__ import annotations


def analyze_contributor_concentration(event_counts: list[int]) -> dict:
    """Measure how concentrated development activity is across contributors."""
    if any(count < 0 for count in event_counts):
        raise ValueError("event counts must be non-negative")

    total_events = sum(event_counts)
    active_counts = [count for count in event_counts if count > 0]
    if total_events == 0:
        return {
            "contributors": len(event_counts),
            "active_contributors": 0,
            "top_contributor_share": 0.0,
            "concentration_index": 0.0,
            "effective_contributors": 0.0,
            "status": "inactive",
        }

    shares = [count / total_events for count in active_counts]
    concentration_index = sum(share * share for share in shares)
    top_share = max(shares)
    effective_contributors = 1.0 / concentration_index

    if top_share >= 0.70 or concentration_index >= 0.50:
        status = "concentrated"
    elif top_share >= 0.50 or concentration_index >= 0.30:
        status = "moderate"
    else:
        status = "distributed"

    return {
        "contributors": len(event_counts),
        "active_contributors": len(active_counts),
        "top_contributor_share": round(top_share, 3),
        "concentration_index": round(concentration_index, 3),
        "effective_contributors": round(effective_contributors, 2),
        "status": status,
    }
