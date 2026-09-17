from dataclasses import dataclass
from statistics import median


@dataclass(frozen=True)
class DeploymentBatchReport:
    deployments: int
    total_changes: int
    median_batch_size: float
    largest_batch_size: int
    oversized_deployments: int
    status: str


def analyze_deployment_batches(
    changes_per_deployment: list[int],
    warning_size: int = 20,
    critical_size: int = 50,
) -> DeploymentBatchReport:
    """Summarize deployment batch size and identify risky large releases."""
    if warning_size <= 0 or critical_size <= warning_size:
        raise ValueError("thresholds must satisfy 0 < warning < critical")
    if any(changes < 0 for changes in changes_per_deployment):
        raise ValueError("change counts cannot be negative")
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
