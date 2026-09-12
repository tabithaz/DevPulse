from statistics import median

from fastapi import FastAPI, Query
from pydantic import BaseModel, Field, field_validator, model_validator

app = FastAPI(
    title="DevPulse API",
    description="API for developer activity and repository analytics.",
    version="0.14.0",
)


class RepositoryActivity(BaseModel):
    name: str = Field(min_length=1)
    commits: int = Field(default=0, ge=0)
    pull_requests: int = Field(default=0, ge=0)
    issues: int = Field(default=0, ge=0)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, name: str) -> str:
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("repository name must not be blank")
        return normalized_name

    @property
    def total_activity(self) -> int:
        return self.commits + self.pull_requests + self.issues


class ActivitySummaryRequest(BaseModel):
    repositories: list[RepositoryActivity]

    @model_validator(mode="after")
    def reject_duplicate_repository_names(self) -> "ActivitySummaryRequest":
        repository_names = [repository.name.casefold() for repository in self.repositories]
        if len(repository_names) != len(set(repository_names)):
            raise ValueError("repository names must be unique")
        return self


class ActivitySummary(BaseModel):
    repositories_tracked: int
    active_repositories: int
    inactive_repositories: int
    activity_coverage_percent: float
    average_events_per_active_repository: float
    median_events_per_repository: float
    repository_activity_range: int
    total_commits: int
    total_pull_requests: int
    total_issues: int
    total_events: int
    commit_share_percent: float
    pull_request_share_percent: float
    issue_share_percent: float
    dominant_activity_type: str | None
    dominant_activity_events: int
    activity_diversity_score: float
    activity_diversity: str | None
    most_active_repository: str | None
    most_active_repository_events: int
    most_active_repository_share_percent: float
    activity_concentration: str | None


def activity_concentration(share_percent: float, total_events: int) -> str | None:
    if total_events == 0:
        return None
    if share_percent >= 75.0:
        return "highly_concentrated"
    if share_percent >= 50.0:
        return "concentrated"
    return "balanced"


def activity_diversity(counts: list[int]) -> tuple[float, str | None]:
    total_events = sum(counts)
    if total_events == 0:
        return 0.0, None

    shares = [count / total_events for count in counts]
    concentration = sum(share * share for share in shares)
    minimum_concentration = 1.0 / len(counts)
    score = round(
        100.0 * (1.0 - concentration) / (1.0 - minimum_concentration),
        1,
    )

    if score >= 70.0:
        label = "diverse"
    elif score >= 40.0:
        label = "moderate"
    else:
        label = "specialized"
    return score, label


def dominant_activity(counts: dict[str, int]) -> tuple[str | None, int]:
    if not counts:
        return None, 0

    highest_count = max(counts.values())
    if highest_count == 0:
        return None, 0

    leaders = [activity_type for activity_type, count in counts.items() if count == highest_count]
    if len(leaders) != 1:
        return None, highest_count

    return leaders[0], highest_count


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "DevPulse API is running"}


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "healthy"}


@app.post("/activity/rankings")
def rank_repository_activity(
    payload: ActivitySummaryRequest,
    limit: int = Query(default=10, ge=1, le=100),
) -> list[dict]:
    total_events = sum(repository.total_activity for repository in payload.repositories)
    ranked = sorted(
        payload.repositories,
        key=lambda repository: (-repository.total_activity, repository.name.casefold()),
    )
    return [
        {
            "rank": index,
            "repository": repository.name,
            "events": repository.total_activity,
            "share_percent": round((repository.total_activity / total_events) * 100, 1)
            if total_events
            else 0.0,
        }
        for index, repository in enumerate(ranked[:limit], start=1)
    ]


@app.post("/activity/summary", response_model=ActivitySummary)
def summarize_activity(payload: ActivitySummaryRequest) -> ActivitySummary:
    repositories_tracked = len(payload.repositories)
    repository_event_counts = [repository.total_activity for repository in payload.repositories]
    active_repositories = sum(1 for count in repository_event_counts if count > 0)
    inactive_repositories = repositories_tracked - active_repositories
    activity_coverage_percent = round((active_repositories / repositories_tracked) * 100, 1) if repositories_tracked else 0.0

    total_commits = sum(repository.commits for repository in payload.repositories)
    total_pull_requests = sum(repository.pull_requests for repository in payload.repositories)
    total_issues = sum(repository.issues for repository in payload.repositories)
    total_events = total_commits + total_pull_requests + total_issues
    average_events_per_active_repository = round(total_events / active_repositories, 1) if active_repositories else 0.0
    median_events_per_repository = round(float(median(repository_event_counts)), 1) if repository_event_counts else 0.0
    repository_activity_range = max(repository_event_counts) - min(repository_event_counts) if repository_event_counts else 0

    def event_share(count: int) -> float:
        return round((count / total_events) * 100, 1) if total_events else 0.0

    activity_counts = {"commits": total_commits, "pull_requests": total_pull_requests, "issues": total_issues}
    dominant_activity_type, dominant_activity_events = dominant_activity(activity_counts)
    diversity_score, diversity_label = activity_diversity(list(activity_counts.values()))

    most_active_repository = min(
        payload.repositories,
        key=lambda repository: (-repository.total_activity, repository.name.casefold()),
        default=None,
    )
    most_active_repository_events = most_active_repository.total_activity if most_active_repository else 0
    most_active_repository_share_percent = round((most_active_repository_events / total_events) * 100, 1) if total_events else 0.0

    return ActivitySummary(
        repositories_tracked=repositories_tracked,
        active_repositories=active_repositories,
        inactive_repositories=inactive_repositories,
        activity_coverage_percent=activity_coverage_percent,
        average_events_per_active_repository=average_events_per_active_repository,
        median_events_per_repository=median_events_per_repository,
        repository_activity_range=repository_activity_range,
        total_commits=total_commits,
        total_pull_requests=total_pull_requests,
        total_issues=total_issues,
        total_events=total_events,
        commit_share_percent=event_share(total_commits),
        pull_request_share_percent=event_share(total_pull_requests),
        issue_share_percent=event_share(total_issues),
        dominant_activity_type=dominant_activity_type,
        dominant_activity_events=dominant_activity_events,
        activity_diversity_score=diversity_score,
        activity_diversity=diversity_label,
        most_active_repository=most_active_repository.name if most_active_repository else None,
        most_active_repository_events=most_active_repository_events,
        most_active_repository_share_percent=most_active_repository_share_percent,
        activity_concentration=activity_concentration(most_active_repository_share_percent, total_events),
    )
