from dataclasses import asdict
import csv
from datetime import datetime
import hashlib
from io import StringIO
import json
import sqlite3
from pathlib import Path
from statistics import median, pstdev
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse

from app.change_failure import analyze_change_failure
from app.deployment_batch import analyze_deployment_batches
from app.deployment_frequency import analyze_deployment_frequency
from app.deployment_rollback import analyze_rollbacks
from app.github_client import (
    GitHubClient,
    GitHubNotFoundError,
    GitHubRateLimitError,
    GitHubServiceError,
    RepositorySnapshot,
    github_client_dependency,
)
from app.lead_time import analyze_lead_time
from app.snapshot_store import (
    IdempotencyConflictError,
    SnapshotStore,
    snapshot_store_dependency,
)
from pydantic import BaseModel, Field, field_validator, model_validator

app = FastAPI(
    title="DevPulse API",
    description="API for developer activity and repository analytics.",
    version="0.17.0",
)

DASHBOARD_PATH = Path(__file__).parent / "static" / "dashboard.html"


def conditional_json_response(request: Request, payload: dict) -> Response:
    """Return a stable ETag and honor conditional requests for stored analytics."""
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    etag = f'"{hashlib.sha256(encoded).hexdigest()}"'
    cache_headers = {
        "ETag": etag,
        "Cache-Control": "private, max-age=0, must-revalidate",
    }
    candidates = {
        candidate.strip().removeprefix("W/")
        for candidate in request.headers.get("if-none-match", "").split(",")
    }
    if "*" in candidates or etag in candidates:
        return Response(status_code=304, headers=cache_headers)
    return JSONResponse(content=payload, headers=cache_headers)


def snapshot_changes(
    current: RepositorySnapshot,
    previous: RepositorySnapshot,
) -> dict[str, int | bool]:
    return {
        "stars": current.stars - previous.stars,
        "forks": current.forks - previous.forks,
        "open_issues": current.open_issues - previous.open_issues,
        "archived_changed": current.archived != previous.archived,
        "default_branch_changed": current.default_branch != previous.default_branch,
    }


def repository_trend(snapshots: list[RepositorySnapshot], repository: str) -> dict:
    """Summarize bounded repository growth from oldest to newest snapshot."""
    empty_metrics = {
        "net_changes": None,
        "per_day": None,
        "change_volatility": None,
    }
    if not snapshots:
        return {
            "repository": repository,
            "status": "no_data",
            "snapshots_analyzed": 0,
            "window": None,
            **empty_metrics,
        }
    if len(snapshots) == 1:
        collected_at = snapshots[0].collected_at
        return {
            "repository": repository,
            "status": "insufficient_data",
            "snapshots_analyzed": 1,
            "window": {
                "started_at": collected_at,
                "ended_at": collected_at,
                "elapsed_days": 0.0,
            },
            **empty_metrics,
        }

    ordered = list(reversed(snapshots))
    oldest, newest = ordered[0], ordered[-1]
    elapsed_seconds = (
        datetime.fromisoformat(newest.collected_at)
        - datetime.fromisoformat(oldest.collected_at)
    ).total_seconds()
    elapsed_days = max(0.0, elapsed_seconds / 86400.0)
    fields = ("stars", "forks", "open_issues")
    net_changes = {
        field: getattr(newest, field) - getattr(oldest, field)
        for field in fields
    }
    interval_changes = {
        field: [
            getattr(current, field) - getattr(previous, field)
            for previous, current in zip(ordered, ordered[1:])
        ]
        for field in fields
    }
    return {
        "repository": repository,
        "status": "ready",
        "snapshots_analyzed": len(ordered),
        "window": {
            "started_at": oldest.collected_at,
            "ended_at": newest.collected_at,
            "elapsed_days": round(elapsed_days, 3),
        },
        "net_changes": net_changes,
        "per_day": {
            field: round(change / elapsed_days, 3) if elapsed_days > 0 else None
            for field, change in net_changes.items()
        },
        "change_volatility": {
            field: round(pstdev(changes), 3)
            for field, changes in interval_changes.items()
        },
    }


def collection_fingerprint(repositories: list[str]) -> str:
    """Create a stable identity for an ordered collection request."""
    encoded = json.dumps(repositories, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def replayed_collection(
    store: SnapshotStore,
    idempotency_key: str | None,
    request_fingerprint: str,
) -> Response | None:
    if idempotency_key is None:
        return None
    try:
        result = store.idempotency_result(idempotency_key, request_fingerprint)
    except IdempotencyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result is None:
        return None
    return JSONResponse(
        status_code=201,
        content=result,
        headers={"Idempotency-Replayed": "true"},
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


class RepositoryTarget(BaseModel):
    owner: str = Field(min_length=1, max_length=39)
    repository: str = Field(min_length=1, max_length=100)

    @field_validator("owner", "repository")
    @classmethod
    def normalize_identifier(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("repository identifiers must not be blank")
        if "/" in normalized or any(character.isspace() for character in normalized):
            raise ValueError("repository identifiers must not contain slashes or whitespace")
        return normalized


class SnapshotCollectionRequest(BaseModel):
    repositories: list[RepositoryTarget] = Field(min_length=1, max_length=25)

    @model_validator(mode="after")
    def reject_duplicate_repositories(self) -> "SnapshotCollectionRequest":
        names = [
            f"{target.owner}/{target.repository}".casefold()
            for target in self.repositories
        ]
        if len(names) != len(set(names)):
            raise ValueError("repositories must be unique")
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


@app.get("/ready")
def readiness_check() -> dict[str, str]:
    """Confirm the service can initialize and query its snapshot database."""
    try:
        store = SnapshotStore.from_environment()
        store.check_connection()
    except (OSError, sqlite3.Error, ValueError) as exc:
        raise HTTPException(status_code=503, detail="snapshot database unavailable") from exc
    return {"status": "ready", "database": "available"}


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
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            min_length=1,
            max_length=128,
            pattern=r"^[A-Za-z0-9._:-]+$",
        ),
    ] = None,
) -> Response:
    fingerprint = collection_fingerprint([f"{owner}/{repository}".casefold()])
    replay = replayed_collection(store, idempotency_key, fingerprint)
    if replay is not None:
        return replay
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

    result = snapshot.to_dict()
    if idempotency_key is None:
        store.save(snapshot)
        return JSONResponse(status_code=201, content=result)
    try:
        result, replayed = store.save_many_once(
            [snapshot], idempotency_key, fingerprint, result
        )
    except IdempotencyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return JSONResponse(
        status_code=201,
        content=result,
        headers={"Idempotency-Replayed": str(replayed).lower()},
    )


@app.post("/github/snapshots/collect", status_code=201)
def collect_github_repository_snapshots(
    payload: SnapshotCollectionRequest,
    client: Annotated[GitHubClient, Depends(github_client_dependency)],
    store: Annotated[SnapshotStore, Depends(snapshot_store_dependency)],
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            min_length=1,
            max_length=128,
            pattern=r"^[A-Za-z0-9._:-]+$",
        ),
    ] = None,
) -> Response:
    """Collect a bounded repository batch and persist it atomically."""
    fingerprint = collection_fingerprint([
        f"{target.owner}/{target.repository}".casefold()
        for target in payload.repositories
    ])
    replay = replayed_collection(store, idempotency_key, fingerprint)
    if replay is not None:
        return replay
    snapshots = []
    for target in payload.repositories:
        try:
            snapshots.append(client.repository_snapshot(target.owner, target.repository))
        except GitHubNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except GitHubRateLimitError as exc:
            detail = "GitHub API rate limit exceeded"
            if exc.reset_at:
                detail += f"; resets at Unix timestamp {exc.reset_at}"
            raise HTTPException(status_code=429, detail=detail) from exc
        except GitHubServiceError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    result = {
        "collected": len(snapshots),
        "repositories": [snapshot.to_dict() for snapshot in snapshots],
    }
    if idempotency_key is None:
        store.save_many(snapshots)
        return JSONResponse(status_code=201, content=result)
    try:
        result, replayed = store.save_many_once(
            snapshots, idempotency_key, fingerprint, result
        )
    except IdempotencyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return JSONResponse(
        status_code=201,
        content=result,
        headers={"Idempotency-Replayed": str(replayed).lower()},
    )


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
        "changes": snapshot_changes(current, previous),
    }


@app.get("/github/{owner}/{repository}/snapshots/trend")
def github_repository_snapshot_trend(
    request: Request,
    owner: str,
    repository: str,
    store: Annotated[SnapshotStore, Depends(snapshot_store_dependency)],
    limit: int = Query(default=30, ge=2, le=365),
) -> Response:
    """Measure repository growth velocity and volatility over stored history."""
    name = f"{owner}/{repository}"
    payload = repository_trend(store.history(name, limit=limit), name)
    return conditional_json_response(request, payload)


@app.get("/github/snapshots/summary")
def github_snapshot_portfolio_summary(
    request: Request,
    store: Annotated[SnapshotStore, Depends(snapshot_store_dependency)],
) -> Response:
    """Summarize the newest stored snapshot for every tracked repository."""
    snapshots = store.latest()
    languages: dict[str, int] = {}
    for snapshot in snapshots:
        language = snapshot.language or "Unknown"
        languages[language] = languages.get(language, 0) + 1

    summary = {
        "repositories_tracked": len(snapshots),
        "active_repositories": sum(not snapshot.archived for snapshot in snapshots),
        "archived_repositories": sum(snapshot.archived for snapshot in snapshots),
        "total_stars": sum(snapshot.stars for snapshot in snapshots),
        "total_forks": sum(snapshot.forks for snapshot in snapshots),
        "total_open_issues": sum(snapshot.open_issues for snapshot in snapshots),
        "languages": dict(sorted(languages.items(), key=lambda item: item[0].casefold())),
        "repositories": [snapshot.to_dict() for snapshot in snapshots],
    }
    return conditional_json_response(request, summary)


@app.get("/github/snapshots/delta")
def github_snapshot_portfolio_delta(
    request: Request,
    store: Annotated[SnapshotStore, Depends(snapshot_store_dependency)],
) -> Response:
    """Compare the latest two snapshots across the tracked portfolio."""
    histories = store.latest_history(limit_per_repository=2)
    repositories = []
    total_changes = {"stars": 0, "forks": 0, "open_issues": 0}
    gaining_stars = 0
    losing_stars = 0

    for repository, history in histories.items():
        current = history[0]
        if len(history) == 1:
            repositories.append({
                "repository": repository,
                "status": "insufficient_data",
                "current_collected_at": current.collected_at,
                "previous_collected_at": None,
                "changes": None,
            })
            continue

        previous = history[1]
        changes = snapshot_changes(current, previous)
        for metric in total_changes:
            total_changes[metric] += int(changes[metric])
        gaining_stars += changes["stars"] > 0
        losing_stars += changes["stars"] < 0
        repositories.append({
            "repository": repository,
            "status": "ready",
            "current_collected_at": current.collected_at,
            "previous_collected_at": previous.collected_at,
            "changes": changes,
        })

    comparable = sum(item["status"] == "ready" for item in repositories)
    payload = {
        "repositories_tracked": len(repositories),
        "comparable_repositories": comparable,
        "repositories_gaining_stars": gaining_stars,
        "repositories_losing_stars": losing_stars,
        "total_changes": total_changes,
        "repositories": repositories,
    }
    return conditional_json_response(request, payload)


@app.get("/github/snapshots/trends")
def github_snapshot_portfolio_trends(
    request: Request,
    store: Annotated[SnapshotStore, Depends(snapshot_store_dependency)],
    limit: int = Query(default=30, ge=2, le=365),
) -> Response:
    """Rank longer-term growth across every tracked repository."""
    histories = store.latest_history(limit_per_repository=limit)
    trends = [
        repository_trend(history, repository)
        for repository, history in histories.items()
    ]
    ready = [trend for trend in trends if trend["status"] == "ready"]
    incomplete = [trend for trend in trends if trend["status"] != "ready"]

    def growth_rank(trend: dict) -> tuple[bool, float, str]:
        stars_per_day = trend["per_day"]["stars"]
        return (
            stars_per_day is None,
            -(stars_per_day or 0.0),
            trend["repository"].casefold(),
        )

    ready.sort(key=growth_rank)
    incomplete.sort(key=lambda trend: trend["repository"].casefold())
    metrics = ("stars", "forks", "open_issues")
    total_per_day = {
        metric: round(sum(
            trend["per_day"][metric]
            for trend in ready
            if trend["per_day"][metric] is not None
        ), 3)
        for metric in metrics
    }
    payload = {
        "repositories_tracked": len(trends),
        "comparable_repositories": len(ready),
        "insufficient_data_repositories": len(incomplete),
        "fastest_growing_repository": (
            ready[0]["repository"]
            if ready and ready[0]["per_day"]["stars"] is not None
            else None
        ),
        "total_net_changes": {
            metric: sum(trend["net_changes"][metric] for trend in ready)
            for metric in metrics
        },
        "total_per_day": total_per_day,
        "repositories": ready + incomplete,
    }
    return conditional_json_response(request, payload)


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
