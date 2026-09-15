from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class ChangeFailureReport:
    total_deployments: int
    failed_deployments: int
    failure_rate_percent: float
    status: str


def analyze_change_failure(
    deployments: list[bool],
    warning_percent: float = 15.0,
    critical_percent: float = 30.0,
) -> ChangeFailureReport:
    if (
        isinstance(warning_percent, bool)
        or isinstance(critical_percent, bool)
        or not isinstance(warning_percent, (int, float))
        or not isinstance(critical_percent, (int, float))
        or not isfinite(warning_percent)
        or not isfinite(critical_percent)
        or warning_percent < 0
        or critical_percent <= warning_percent
    ):
        raise ValueError("thresholds must be finite numbers satisfying 0 <= warning < critical")
    if not isinstance(deployments, list) or any(
        not isinstance(succeeded, bool) for succeeded in deployments
    ):
        raise ValueError("deployments must be a list of booleans")

    if not deployments:
        return ChangeFailureReport(0, 0, 0.0, "no_data")

    failed = sum(1 for succeeded in deployments if not succeeded)
    failure_rate = failed / len(deployments) * 100.0

    if failure_rate < warning_percent:
        status = "healthy"
    elif failure_rate < critical_percent:
        status = "watch"
    else:
        status = "critical"

    return ChangeFailureReport(
        total_deployments=len(deployments),
        failed_deployments=failed,
        failure_rate_percent=round(failure_rate, 2),
        status=status,
    )
