from dataclasses import dataclass


@dataclass(frozen=True)
class ReleaseStabilityReport:
    release_count: int
    rollback_count: int
    hotfix_count: int
    clean_release_rate_percent: float
    intervention_rate_percent: float
    status: str


def analyze_release_stability(
    releases: list[tuple[bool, bool]],
    warning_intervention_percent: float = 15.0,
    critical_intervention_percent: float = 30.0,
) -> ReleaseStabilityReport:
    if (
        warning_intervention_percent < 0
        or critical_intervention_percent <= warning_intervention_percent
    ):
        raise ValueError("thresholds must satisfy 0 <= warning < critical")

    if not releases:
        return ReleaseStabilityReport(0, 0, 0, 0.0, 0.0, "no_data")

    rollback_count = sum(1 for rolled_back, _ in releases if rolled_back)
    hotfix_count = sum(1 for _, needed_hotfix in releases if needed_hotfix)
    intervention_count = sum(
        1 for rolled_back, needed_hotfix in releases if rolled_back or needed_hotfix
    )
    release_count = len(releases)
    intervention_rate = intervention_count / release_count * 100.0
    clean_release_rate = 100.0 - intervention_rate

    if intervention_rate < warning_intervention_percent:
        status = "stable"
    elif intervention_rate < critical_intervention_percent:
        status = "watch"
    else:
        status = "unstable"

    return ReleaseStabilityReport(
        release_count=release_count,
        rollback_count=rollback_count,
        hotfix_count=hotfix_count,
        clean_release_rate_percent=round(clean_release_rate, 2),
        intervention_rate_percent=round(intervention_rate, 2),
        status=status,
    )
