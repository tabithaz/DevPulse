from dataclasses import dataclass
from statistics import median


@dataclass(frozen=True)
class DeploymentFrequencyReport:
    deployment_count: int
    median_gap_days: float
    longest_gap_days: float
    deployments_per_week: float
    status: str


def analyze_deployment_frequency(deployment_days: list[float]) -> DeploymentFrequencyReport:
    if any(day < 0 for day in deployment_days):
        raise ValueError("deployment days cannot be negative")
    if deployment_days != sorted(deployment_days):
        raise ValueError("deployment days must be sorted")
    if not deployment_days:
        return DeploymentFrequencyReport(0, 0.0, 0.0, 0.0, "no_data")
    if len(deployment_days) == 1:
        return DeploymentFrequencyReport(1, 0.0, 0.0, 0.0, "insufficient_data")

    gaps = [deployment_days[i] - deployment_days[i - 1] for i in range(1, len(deployment_days))]
    span = deployment_days[-1] - deployment_days[0]
    per_week = ((len(deployment_days) - 1) / span * 7.0) if span > 0 else float(len(deployment_days))
    median_gap = float(median(gaps))
    longest_gap = max(gaps)

    if median_gap <= 2 and longest_gap <= 7:
        status = "frequent"
    elif median_gap <= 7 and longest_gap <= 14:
        status = "steady"
    else:
        status = "sporadic"

    return DeploymentFrequencyReport(
        len(deployment_days), round(median_gap, 2), round(longest_gap, 2), round(per_week, 2), status
    )
