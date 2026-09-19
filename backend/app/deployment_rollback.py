from dataclasses import dataclass


@dataclass(frozen=True)
class RollbackReport:
    deployments: int
    rollbacks: int
    rollback_rate_percent: float
    consecutive_rollbacks: int
    status: str


def analyze_rollbacks(
    outcomes: list[bool],
    warning_percent: float = 10.0,
    critical_percent: float = 25.0,
) -> RollbackReport:
    """Summarize rollback pressure from deployment outcomes.

    Each outcome is True when a deployment completed without a rollback and
    False when it required a rollback.
    """
    if warning_percent < 0 or critical_percent <= warning_percent:
        raise ValueError("rollback thresholds must be ordered and non-negative")

    if not outcomes:
        return RollbackReport(0, 0, 0.0, 0, "no_data")

    rollbacks = 0
    current_run = 0
    longest_run = 0
    for successful in outcomes:
        if successful:
            current_run = 0
            continue
        rollbacks += 1
        current_run += 1
        longest_run = max(longest_run, current_run)

    rate = rollbacks / len(outcomes) * 100.0
    if longest_run >= 2 or rate >= critical_percent:
        status = "critical"
    elif rate >= warning_percent:
        status = "watch"
    else:
        status = "healthy"

    return RollbackReport(
        deployments=len(outcomes),
        rollbacks=rollbacks,
        rollback_rate_percent=round(rate, 2),
        consecutive_rollbacks=longest_run,
        status=status,
    )
