from dataclasses import dataclass


@dataclass(frozen=True)
class DeliveryReadiness:
    score: float
    status: str
    blockers: tuple[str, ...]


def analyze_delivery_readiness(
    test_pass_rate: float,
    coverage_percent: float,
    open_critical_issues: int,
    days_since_release: int,
) -> DeliveryReadiness:
    if isinstance(test_pass_rate, bool) or not isinstance(test_pass_rate, (int, float)):
        raise ValueError("test_pass_rate must be numeric")
    if isinstance(coverage_percent, bool) or not isinstance(coverage_percent, (int, float)):
        raise ValueError("coverage_percent must be numeric")
    if isinstance(open_critical_issues, bool) or not isinstance(open_critical_issues, int):
        raise ValueError("open_critical_issues must be an integer")
    if isinstance(days_since_release, bool) or not isinstance(days_since_release, int):
        raise ValueError("days_since_release must be an integer")

    if not 0 <= test_pass_rate <= 1:
        raise ValueError("test_pass_rate must be between 0 and 1")
    if not 0 <= coverage_percent <= 100:
        raise ValueError("coverage_percent must be between 0 and 100")
    if open_critical_issues < 0 or days_since_release < 0:
        raise ValueError("counts cannot be negative")

    score = (
        45 * test_pass_rate
        + 30 * (coverage_percent / 100)
        + 15 * min(days_since_release / 14, 1)
        + (10 if open_critical_issues == 0 else 0)
    )

    blockers = []
    if test_pass_rate < 0.95:
        blockers.append("test_reliability")
    if coverage_percent < 70:
        blockers.append("coverage")
    if open_critical_issues:
        blockers.append("critical_issues")

    if score >= 85 and not blockers:
        status = "ready"
    elif score >= 65 and "critical_issues" not in blockers:
        status = "review"
    else:
        status = "blocked"

    return DeliveryReadiness(round(score, 2), status, tuple(blockers))
