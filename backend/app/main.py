from dataclasses import asdict
import csv
from io import StringIO
from pathlib import Path
from statistics import median
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from fastapi.responses import FileResponse

from app.change_failure import analyze_change_failure
from app.deployment_batch import analyze_deployment_batches
from app.deployment_frequency import analyze_deployment_frequency
from app.deployment_rollback import analyze_rollbacks
from app.github_client import (
    GitHubClient,
    GitHubNotFoundError,
    GitHubRateLimitError,
    GitHubServiceError,
    github_client_dependency,
)
from app.lead_time import analyze_lead_time
from app.snapshot_store import SnapshotStore, snapshot_store_dependency
from pydantic import BaseModel, Field, field_validator, model_validator

app = FastAPI(
    title="DevPulse API",
    description="API for developer activity and repository analytics.",
    version="0.16.0",
)

DASHBOARD_PATH = Path(__file__).parent / "static" / "dashboard.html"


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


class LeadTimeRequest(BaseModel):
    lead_times_hours: list[Annotated[float, Field(ge=0)]]
    warning_hours: float = Field(default=48.0, gt=0)
    critical_hours: float = Field(default=120.0, gt=0)

    @model_validator(mode="after")
    def validate_threshold_order(self) -> "LeadTimeRequest":
        if self.critical_hours <= self.warning_hours:
            raise ValueError("critical_hours must be greater than warning_hours")
        return self


class DeploymentHealthRequest(BaseModel):
    deployment_days: list[Annotated[float, Field(ge=0)]]
    changes_per_deployment: list[Annotated[int, Field(ge=0)]]
    outcomes: list[bool]

    @model_validator(mode="after")
    def validate_deployment_history(self) -> "DeploymentHealthRequest":
        entry_counts = {
            len(self.deployment_days),
            len(self.changes_per_deployment),
            len(self.outcomes),
        }
        if len(entry_counts) != 1:
            raise ValueError("deployment inputs must contain the same number of entries")
        if self.deployment_days != sorted(self.deployment_days):
            raise ValueError("deployment_days must be sorted")
        return self


class ActivitySummary(BaseModel):
    repositories_tracked: int
    active_repositories: int
    inactive_repositories: int
    activity_coverage_percent: float
    average_events_per_repository: float
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


@app.get("/dashboard", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(DASHBOARD_PATH, media_type="text/html")


@app.get("/github/{owner}/{repository}/snapshot")
def github_repository_snapshot(
    owner: str,
    repository: str,
    client: Annotated[GitHubClient, Depends(github_client_dependency)],
) -> dict:
    try:
        return client.repository_snapshot(owner, repository).to_dict()
    except GitHubNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GitHubRateLimitError as exc:
        detail = "GitHub API rate limit exceeded"
        if exc.reset_at:
            detail += f"; resets at Unix timestamp {exc.reset_at}"
        raise HTTPException(status_code=429, detail=detail) from exc
    except GitHubServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/github/{owner}/{repository}/snapshots", status_code=201)
def collect_github_repository_snapshot(
    owner: str,
    repository: str,
    client: Annotated[GitHubClient, Depends(github_client_dependency)],
    store: Annotated[SnapshotStore, Depends(snapshot_store_dependency)],
) -> dict:
    try:
        snapshot = client.repository_snapshot(owner, repository)
    except GitHubNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GitHubRateLimitError as exc:
        detail = "GitHub API rate limit exceeded"
        if exc.reset_at:
            detail += f"; resets at Unix timestamp {exc.reset_at}"
        raise HTTPException(status_code=429, detail=detail) from exc
    except GitHubServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    store.save(snapshot)
    return snapshot.to_dict()


@app.get("/github/{owner}/{repository}/snapshots")
def github_repository_snapshot_history(
    owner: str,
    repository: str,
    store: Annotated[SnapshotStore, Depends(snapshot_store_dependency)],
    limit: int = Query(default=30, ge=1, le=365),
) -> list[dict]:
    name = f"{owner}/{repository}"
    return [snapshot.to_dict() for snapshot in store.history(name, limit)]


@app.get("/github/{owner}/{repository}/snapshots/export")
def export_github_repository_snapshots(
    owner: str,
    repository: str,
    store: Annotated[SnapshotStore, Depends(snapshot_store_dependency)],
    limit: int = Query(default=365, ge=1, le=365),
) -> Response:
    """Download stored snapshot history without making a GitHub API request."""
    def safe_text(value: str | None) -> str:
        if value is None:
            return ""
        return f"'{value}" if value.lstrip().startswith(("=", "+", "-", "@")) else value

    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(("collected_at", "repository", "stars", "forks", "open_issues",
                     "language", "archived", "default_branch"))
    for snapshot in store.history(f"{owner}/{repository}", limit=limit):
        writer.writerow((snapshot.collected_at, safe_text(snapshot.repository),
                         snapshot.stars, snapshot.forks, snapshot.open_issues,
                         safe_text(snapshot.language), snapshot.archived,
                         safe_text(snapshot.default_branch)))

    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="devpulse-snapshots.csv"'},
    )


@app.get("/github/{owner}/{repository}/snapshots/delta")
def github_repository_snapshot_delta(
    owner: str,
    repository: str,
    store: Annotated[SnapshotStore, Depends(snapshot_store_dependency)],
) -> dict:
    """Compare the two most recently collected snapshots without calling GitHub."""
    name = f"{owner}/{repository}"
    history = store.history(name, limit=2)
    if not history:
        return {"repository": name, "status": "no_data", "current": None,
                "previous_collected_at": None, "changes": None}

    current = history[0]
    if len(history) == 1:
        return {"repository": name, "status": "insufficient_data",
                "current": current.to_dict(), "previous_collected_at": None,
                "changes": None}

    previous = history[1]
    return {
        "repository": name,
        "status": "ready",
        "current": current.to_dict(),
        "previous_collected_at": previous.collected_at,
        "changes": {
            "stars": current.stars - previous.stars,
            "forks": current.forks - previous.forks,
            "open_issues": current.open_issues - previous.open_issues,
            "archived_changed": current.archived != previous.archived,
            "default_branch_changed": current.default_branch != previous.default_branch,
        },
    }


@app.get("/github/snapshots/summary")
def github_snapshot_portfolio_summary(
    store: Annotated[SnapshotStore, Depends(snapshot_store_dependency)],
) -> dict:
    """Summarize the newest stored snapshot for every tracked repository."""
    snapshots = store.latest()
    languages: dict[str, int] = {}
    for snapshot in snapshots:
        language = snapshot.language or "Unknown"
        languages[language] = languages.get(language, 0) + 1

    return {
        "repositories_tracked": len(snapshots),
        "active_repositories": sum(not snapshot.archived for snapshot in snapshots),
        "archived_repositories": sum(snapshot.archived for snapshot in snapshots),
        "total_stars": sum(snapshot.stars for snapshot in snapshots),
        "total_forks": sum(snapshot.forks for snapshot in snapshots),
        "total_open_issues": sum(snapshot.open_issues for snapshot in snapshots),
        "languages": dict(sorted(languages.items(), key=lambda item: item[0].casefold())),
        "repositories": [snapshot.to_dict() for snapshot in snapshots],
    }


@app.post("/delivery/lead-time")
def lead_time_report(payload: LeadTimeRequest) -> dict:
    report = analyze_lead_time(
        payload.lead_times_hours,
        warning_hours=payload.warning_hours,
        critical_hours=payload.critical_hours,
    )
    return asdict(report)


@app.post("/deployments/health")
def deployment_health(payload: DeploymentHealthRequest) -> dict:
    frequency = analyze_deployment_frequency(payload.deployment_days)
    batch_size = analyze_deployment_batches(payload.changes_per_deployment)
    rollbacks = analyze_rollbacks(payload.outcomes)
    change_failure = analyze_change_failure(payload.outcomes)

    component_statuses = {
        frequency.status,
        batch_size.status,
        rollbacks.status,
        change_failure.status,
    }
    if component_statuses == {"no_data"}:
        status = "no_data"
    elif component_statuses & {"critical", "high_risk", "sporadic"}:
        status = "critical"
    elif component_statuses & {"watch", "steady", "insufficient_data"}:
        status = "watch"
    else:
        status = "healthy"

    return {
        "status": status,
        "frequency": asdict(frequency),
        "batch_size": asdict(batch_size),
        "rollbacks": asdict(rollbacks),
        "change_failure": asdict(change_failure),
    }


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
    average_events_per_repository = round(total_events / repositories_tracked, 1) if repositories_tracked else 0.0
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
        average_events_per_repository=average_events_per_repository,
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
