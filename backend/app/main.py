from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(
    title="DevPulse API",
    description="API for developer activity and repository analytics.",
    version="0.6.0",
)


class RepositoryActivity(BaseModel):
    name: str = Field(min_length=1)
    commits: int = Field(default=0, ge=0)
    pull_requests: int = Field(default=0, ge=0)
    issues: int = Field(default=0, ge=0)

    @property
    def total_activity(self) -> int:
        return self.commits + self.pull_requests + self.issues


class ActivitySummaryRequest(BaseModel):
    repositories: list[RepositoryActivity]


class ActivitySummary(BaseModel):
    repositories_tracked: int
    active_repositories: int
    activity_coverage_percent: float
    average_events_per_active_repository: float
    total_commits: int
    total_pull_requests: int
    total_issues: int
    total_events: int
    most_active_repository: str | None
    most_active_repository_events: int


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "DevPulse API is running"}


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "healthy"}


@app.post("/activity/summary", response_model=ActivitySummary)
def summarize_activity(payload: ActivitySummaryRequest) -> ActivitySummary:
    repositories_tracked = len(payload.repositories)
    active_repositories = sum(
        1 for repository in payload.repositories if repository.total_activity > 0
    )
    activity_coverage_percent = (
        round((active_repositories / repositories_tracked) * 100, 1)
        if repositories_tracked
        else 0.0
    )

    total_commits = sum(repository.commits for repository in payload.repositories)
    total_pull_requests = sum(
        repository.pull_requests for repository in payload.repositories
    )
    total_issues = sum(repository.issues for repository in payload.repositories)
    total_events = total_commits + total_pull_requests + total_issues
    average_events_per_active_repository = (
        round(total_events / active_repositories, 1) if active_repositories else 0.0
    )

    most_active_repository = max(
        payload.repositories,
        key=lambda repository: (repository.total_activity, repository.name),
        default=None,
    )

    return ActivitySummary(
        repositories_tracked=repositories_tracked,
        active_repositories=active_repositories,
        activity_coverage_percent=activity_coverage_percent,
        average_events_per_active_repository=average_events_per_active_repository,
        total_commits=total_commits,
        total_pull_requests=total_pull_requests,
        total_issues=total_issues,
        total_events=total_events,
        most_active_repository=(
            most_active_repository.name if most_active_repository else None
        ),
        most_active_repository_events=(
            most_active_repository.total_activity if most_active_repository else 0
        ),
    )
