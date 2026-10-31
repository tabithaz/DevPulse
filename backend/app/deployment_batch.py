from dataclasses import dataclass
from statistics import median
from sys import maxsize


@dataclass(frozen=True)
class DeploymentBatchReport:
    deployments: int
    total_changes: int
    median_batch_size: float
    largest_batch_size: int
    oversized_deployments: int
    status: str


def _valid_count(value: object) -> bool:
    return type(value) is int and 0 <= value <= maxsize


def analyze_deployment_batches(
    changes_per_deployment: list[int],
    warning_size: int = 20,
    critical_size: int = 50,
) -> DeploymentBatchReport:
    """Summarize deployment batch size and identify risky large releases."""
    if (not _valid_count(warning_size) or not _valid_count(critical_size)
            or warning_size == 0 or critical_size <= warning_size):
        raise ValueError("thresholds must satisfy 0 < warning < critical with integer sizes")
    if any(not _valid_count(changes) for changes in changes_per_deployment):
        raise ValueError("change counts must be non-negative integers within platform limits")
    if not changes_per_deployment:
        return DeploymentBatchReport(0, 0, 0.0, 0, 0, "no_data")

    largest = max(changes_per_deployment)
    oversized = sum(changes >= warning_size for changes in changes_per_deployment)
    oversized_rate = oversized / len(changes_per_deployment)

    if largest >= critical_size or oversized_rate >= 0.5:
        status = "high_risk"
    elif oversized:
        status = "watch"
    else:
        status = "healthy"

    return DeploymentBatchReport(
        deployments=len(changes_per_deployment),
        total_changes=sum(changes_per_deployment),
        median_batch_size=round(float(median(changes_per_deployment)), 2),
        largest_batch_size=largest,
        oversized_deployments=oversized,
        status=status,
    )
