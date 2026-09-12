from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkloadBalance:
    repositories: int
    mean_events: float
    max_deviation_percent: float
    balance_score: float
    classification: str


def analyze_workload_balance(event_counts: list[int]) -> WorkloadBalance:
    if any(count < 0 for count in event_counts):
        raise ValueError("event counts must be non-negative")
    if not event_counts:
        return WorkloadBalance(0, 0.0, 0.0, 100.0, "empty")

    mean_events = sum(event_counts) / len(event_counts)
    if mean_events == 0:
        return WorkloadBalance(len(event_counts), 0.0, 0.0, 100.0, "balanced")

    max_deviation = max(abs(count - mean_events) for count in event_counts)
    max_deviation_percent = (max_deviation / mean_events) * 100.0
    balance_score = max(0.0, 100.0 - max_deviation_percent)

    if balance_score >= 80.0:
        classification = "balanced"
    elif balance_score >= 50.0:
        classification = "uneven"
    else:
        classification = "skewed"

    return WorkloadBalance(
        repositories=len(event_counts),
        mean_events=round(mean_events, 1),
        max_deviation_percent=round(max_deviation_percent, 1),
        balance_score=round(balance_score, 1),
        classification=classification,
    )
