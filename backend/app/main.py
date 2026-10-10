from dataclasses import asdict
import base64
import binascii
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
from io import StringIO
import json
import logging
import os
import re
import sqlite3
import time
from pathlib import Path
from statistics import median, pstdev
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.gzip import GZipMiddleware

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
from app.http_metrics import RequestMetrics, render_request_metrics
from app.snapshot_store import (
    IdempotencyConflictError,
    SnapshotStore,
    snapshot_store_dependency,
)
from pydantic import BaseModel, Field, field_validator, model_validator

app = FastAPI(
    title="DevPulse API",
    description="API for developer activity and repository analytics.",
    version="0.24.0",
)
app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=6)

DASHBOARD_PATH = Path(__file__).parent / "static" / "dashboard.html"
MAX_WEBHOOK_BYTES = 256 * 1024
MANUAL_COLLECTION_PATH = re.compile(r"^/github/[^/]+/[^/]+/snapshots$")
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
request_metrics = RequestMetrics()
LOGGER = logging.getLogger("devpulse.requests")


def github_rate_limit_http_error(exc: GitHubRateLimitError) -> HTTPException:
    """Translate GitHub quota exhaustion into actionable client backoff metadata."""
    detail = "GitHub API rate limit exceeded"
    headers: dict[str, str] = {}
    if exc.reset_at:
        detail += f"; resets at Unix timestamp {exc.reset_at}"
        try:
            reset_at = int(exc.reset_at)
            if reset_at >= 0:
                headers["X-RateLimit-Reset"] = str(reset_at)
                headers["Retry-After"] = str(max(0, reset_at - int(time.time())))
        except ValueError:
            pass
    return HTTPException(status_code=429, detail=detail, headers=headers)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Apply browser security controls without breaking interactive API docs."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = (
        "camera=(), geolocation=(), microphone=(), payment=(), usb=()"
    )
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    if request.url.path == "/dashboard":
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; base-uri 'none'; form-action 'self'; "
            "frame-ancestors 'none'; connect-src 'self'; "
            "img-src 'self' data:; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'"
        )
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
    return response


@app.middleware("http")
async def trace_http_requests(request: Request, call_next):
    """Propagate safe request IDs and emit one structured completion event."""
    supplied_request_id = request.headers.get("X-Request-ID", "")
    request_id = (
        supplied_request_id
        if REQUEST_ID_PATTERN.fullmatch(supplied_request_id)
        else uuid4().hex
    )
    request.state.request_id = request_id
    started_at = time.perf_counter()
    try:
        response = await call_next(request)
    except BaseException:
        LOGGER.exception(
            json.dumps(
                {
                    "event": "http_request_completed",
                    "request_id": request_id,
                    "method": request.method,
                    "route": "unhandled",
                    "status": 500,
                    "duration_ms": round(
                        (time.perf_counter() - started_at) * 1000,
                        3,
                    ),
                },
                separators=(",", ":"),
            )
        )
        raise
    route = request.scope.get("route")
    route_path = getattr(route, "path", "unmatched")
    response.headers["X-Request-ID"] = request_id
    LOGGER.info(
        json.dumps(
            {
                "event": "http_request_completed",
                "request_id": request_id,
                "method": request.method,
                "route": route_path,
                "status": response.status_code,
                "duration_ms": round(
                    (time.perf_counter() - started_at) * 1000,
                    3,
                ),
            },
            separators=(",", ":"),
        )
    )
    return response


@app.middleware("http")
async def observe_http_requests(request: Request, call_next):
    """Record bounded request-rate, error, and latency metrics."""
    started_at = time.perf_counter()
    request_metrics.begin()
    try:
        response = await call_next(request)
    except BaseException:
        request_metrics.observe(
            request.method,
            "unhandled",
            500,
            time.perf_counter() - started_at,
        )
        raise
    route = request.scope.get("route")
    route_path = getattr(route, "path", "unmatched")
    request_metrics.observe(
        request.method,
        route_path,
        response.status_code,
        time.perf_counter() - started_at,
    )
    return response


@app.middleware("http")
async def protect_manual_collection(request: Request, call_next):
    """Require an API key for manual snapshot writes when configured."""
    expected_key = os.getenv("DEVPULSE_API_KEY", "")
    is_manual_collection = request.method == "POST" and (
        request.url.path == "/github/snapshots/collect"
        or MANUAL_COLLECTION_PATH.fullmatch(request.url.path) is not None
    )
    if expected_key and is_manual_collection:
        supplied_key = request.headers.get("X-API-Key", "")
        if not supplied_key or not hmac.compare_digest(supplied_key, expected_key):
            return JSONResponse(
                status_code=401,
                content={"detail": "valid X-API-Key required"},
                headers={"WWW-Authenticate": "ApiKey"},
            )
    return await call_next(request)


def spreadsheet_safe_text(value: str | None) -> str:
    """Prevent text fields from being interpreted as spreadsheet formulas."""
    if value is None:
        return ""
    return f"'{value}" if value.lstrip().startswith(("=", "+", "-", "@")) else value


def encode_snapshot_cursor(repository: str, collected_at: str) -> str:
    payload = json.dumps(
        {"repository": repository, "collected_at": collected_at},
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_snapshot_cursor(cursor: str, repository: str) -> str:
    try:
        padding = "=" * (-len(cursor) % 4)
        decoded = base64.b64decode(
            cursor + padding,
            altchars=b"-_",
            validate=True,
        )
        payload = json.loads(decoded)
        collected_at = payload["collected_at"]
        if payload["repository"] != repository or not isinstance(collected_at, str):
            raise ValueError
        datetime.fromisoformat(collected_at)
        return collected_at
    except (binascii.Error, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=422,
            detail="invalid snapshot cursor for repository",
        ) from error


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


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def prometheus_label(value: str) -> str:
    """Escape a value for use inside a Prometheus label string."""
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def portfolio_snapshot_freshness(
    snapshots: list[RepositorySnapshot],
    max_age_hours: float,
    now: datetime,
) -> dict:
    """Classify latest repository snapshots against a collection-age SLA."""
    threshold = timedelta(hours=max_age_hours)
    repositories = []
    for snapshot in snapshots:
        collected_at = datetime.fromisoformat(snapshot.collected_at)
        if collected_at.tzinfo is None or collected_at.utcoffset() is None:
            collected_at = collected_at.replace(tzinfo=timezone.utc)
        else:
            collected_at = collected_at.astimezone(timezone.utc)
        age_hours = max(0.0, (now - collected_at).total_seconds() / 3600.0)
        stale = age_hours > max_age_hours
        repositories.append({
            "repository": snapshot.repository,
            "status": "stale" if stale else "fresh",
            "collected_at": snapshot.collected_at,
            "age_hours": round(age_hours, 3),
            "stale_by_hours": round(max(0.0, age_hours - max_age_hours), 3),
            "becomes_stale_at": (collected_at + threshold).isoformat(),
        })

    repositories.sort(key=lambda item: (
        item["status"] != "stale",
        -item["age_hours"],
        item["repository"].casefold(),
    ))
    stale_count = sum(item["status"] == "stale" for item in repositories)
    fresh = [item for item in repositories if item["status"] == "fresh"]
    ages = [item["age_hours"] for item in repositories]
    return {
        "status": "no_data" if not repositories else ("stale" if stale_count else "fresh"),
        "evaluated_at": now.isoformat(),
        "max_age_hours": max_age_hours,
        "repositories_tracked": len(repositories),
        "fresh_repositories": len(repositories) - stale_count,
        "stale_repositories": stale_count,
        "freshest_snapshot_age_hours": min(ages) if ages else None,
        "stalest_snapshot_age_hours": max(ages) if ages else None,
        "next_stale_at": min(
            (item["becomes_stale_at"] for item in fresh),
            default=None,
        ),
        "repositories": repositories,
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


@app.get("/metrics", include_in_schema=False)
def prometheus_metrics(
    store: Annotated[SnapshotStore, Depends(snapshot_store_dependency)],
    max_age_hours: float = Query(default=24.0, gt=0, le=8760),
) -> Response:
    """Expose portfolio state and snapshot freshness for Prometheus scrapers."""
    snapshots = store.latest()
    freshness = portfolio_snapshot_freshness(snapshots, max_age_hours, utc_now())
    lines = [
        "# HELP devpulse_repositories_tracked Number of repositories in the portfolio.",
        "# TYPE devpulse_repositories_tracked gauge",
        f"devpulse_repositories_tracked {len(snapshots)}",
        "# HELP devpulse_repositories_archived Number of archived repositories.",
        "# TYPE devpulse_repositories_archived gauge",
        f"devpulse_repositories_archived {sum(item.archived for item in snapshots)}",
        "# HELP devpulse_stars_total Stars across the latest repository snapshots.",
        "# TYPE devpulse_stars_total gauge",
        f"devpulse_stars_total {sum(item.stars for item in snapshots)}",
        "# HELP devpulse_forks_total Forks across the latest repository snapshots.",
        "# TYPE devpulse_forks_total gauge",
        f"devpulse_forks_total {sum(item.forks for item in snapshots)}",
        "# HELP devpulse_open_issues_total Open issues across the latest repository snapshots.",
        "# TYPE devpulse_open_issues_total gauge",
        f"devpulse_open_issues_total {sum(item.open_issues for item in snapshots)}",
        "# HELP devpulse_snapshots_stale Number of repositories outside the snapshot freshness SLA.",
        "# TYPE devpulse_snapshots_stale gauge",
        f"devpulse_snapshots_stale {freshness['stale_repositories']}",
        "# HELP devpulse_snapshot_age_seconds Age of the latest repository snapshot.",
        "# TYPE devpulse_snapshot_age_seconds gauge",
        "# HELP devpulse_snapshot_stale Whether a repository is outside the freshness SLA.",
        "# TYPE devpulse_snapshot_stale gauge",
    ]
    for item in freshness["repositories"]:
        label = prometheus_label(item["repository"])
        lines.append(
            f'devpulse_snapshot_age_seconds{{repository="{label}"}} '
            f'{item["age_hours"] * 3600:g}'
        )
        lines.append(
            f'devpulse_snapshot_stale{{repository="{label}"}} '
            f'{int(item["status"] == "stale")}'
        )
    lines.extend(render_request_metrics(request_metrics.snapshot()))
    return Response(
        content="\n".join(lines) + "\n",
        media_type="text/plain; version=0.0.4",
    )


@app.post("/github/webhooks", status_code=202)
async def github_webhook(
    request: Request,
    client: Annotated[GitHubClient, Depends(github_client_dependency)],
    store: Annotated[SnapshotStore, Depends(snapshot_store_dependency)],
    github_event: Annotated[
        str,
        Header(alias="X-GitHub-Event", min_length=1, max_length=100),
    ],
    delivery_id: Annotated[
        str,
        Header(
            alias="X-GitHub-Delivery",
            min_length=1,
            max_length=100,
            pattern=r"^[A-Za-z0-9-]+$",
        ),
    ],
    signature: Annotated[
        str | None,
        Header(alias="X-Hub-Signature-256", max_length=100),
    ] = None,
) -> Response:
    """Verify a GitHub webhook and collect a retry-safe repository snapshot."""
    secret = os.getenv("GITHUB_WEBHOOK_SECRET", "")
    if not secret:
        raise HTTPException(status_code=503, detail="GitHub webhook is not configured")

    body = await request.body()
    if len(body) > MAX_WEBHOOK_BYTES:
        raise HTTPException(status_code=413, detail="GitHub webhook payload is too large")
    expected = "sha256=" + hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    if signature is None or not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401, detail="invalid GitHub webhook signature")

    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="invalid GitHub webhook payload") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="invalid GitHub webhook payload")

    if github_event == "ping":
        return JSONResponse(status_code=202, content={"status": "pong"})
    if github_event not in {"push", "repository"}:
        return JSONResponse(
            status_code=202,
            content={"status": "ignored", "event": github_event},
        )

    full_name = payload.get("repository", {}).get("full_name")
    if not isinstance(full_name, str) or full_name.count("/") != 1:
        raise HTTPException(status_code=422, detail="webhook repository is invalid")
    owner, repository = full_name.split("/", 1)
    try:
        target = RepositoryTarget(owner=owner, repository=repository)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="webhook repository is invalid") from exc

    idempotency_key = f"webhook:{delivery_id}"
    fingerprint = hashlib.sha256(body).hexdigest()
    try:
        replay = store.idempotency_result(idempotency_key, fingerprint)
    except IdempotencyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if replay is not None:
        return JSONResponse(
            status_code=202,
            content=replay,
            headers={"Idempotency-Replayed": "true"},
        )

    try:
        snapshot = client.repository_snapshot(target.owner, target.repository)
    except GitHubNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GitHubRateLimitError as exc:
        raise github_rate_limit_http_error(exc) from exc
    except GitHubServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    result = {
        "status": "collected",
        "event": github_event,
        "delivery_id": delivery_id,
        "repository": snapshot.to_dict(),
    }
    try:
        result, replayed = store.save_many_once(
            [snapshot], idempotency_key, fingerprint, result, trigger="webhook"
        )
    except IdempotencyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return JSONResponse(
        status_code=202,
        content=result,
        headers={"Idempotency-Replayed": str(replayed).lower()},
    )


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
        raise github_rate_limit_http_error(exc) from exc
    except GitHubServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/github/rate-limit")
def github_rate_limit(
    client: Annotated[GitHubClient, Depends(github_client_dependency)],
) -> dict:
    """Expose collection capacity without revealing GitHub credentials."""
    try:
        return client.rate_limit().to_dict()
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
        raise github_rate_limit_http_error(exc) from exc
    except GitHubServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    result = snapshot.to_dict()
    if idempotency_key is None:
        store.save(snapshot, trigger="api")
        return JSONResponse(status_code=201, content=result)
    try:
        result, replayed = store.save_many_once(
            [snapshot], idempotency_key, fingerprint, result, trigger="api"
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
            raise github_rate_limit_http_error(exc) from exc
        except GitHubServiceError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    result = {
        "collected": len(snapshots),
        "repositories": [snapshot.to_dict() for snapshot in snapshots],
    }
    if idempotency_key is None:
        store.save_many(snapshots, trigger="batch")
        return JSONResponse(status_code=201, content=result)
    try:
        result, replayed = store.save_many_once(
            snapshots, idempotency_key, fingerprint, result, trigger="batch"
        )
    except IdempotencyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return JSONResponse(
        status_code=201,
        content=result,
        headers={"Idempotency-Replayed": str(replayed).lower()},
    )


@app.get("/github/snapshots/collections")
def github_snapshot_collection_runs(
    store: Annotated[SnapshotStore, Depends(snapshot_store_dependency)],
    limit: int = Query(default=50, ge=1, le=1000),
) -> list[dict]:
    """List successful snapshot collection runs for operational auditing."""
    return store.collection_runs(limit)


@app.get("/github/{owner}/{repository}/snapshots")
def github_repository_snapshot_history(
    owner: str,
    repository: str,
    store: Annotated[SnapshotStore, Depends(snapshot_store_dependency)],
    limit: int = Query(default=30, ge=1, le=365),
) -> list[dict]:
    name = f"{owner}/{repository}"
    return [snapshot.to_dict() for snapshot in store.history(name, limit)]


@app.get("/github/{owner}/{repository}/snapshots/page")
def github_repository_snapshot_page(
    owner: str,
    repository: str,
    store: Annotated[SnapshotStore, Depends(snapshot_store_dependency)],
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None, min_length=1, max_length=1000),
) -> dict:
    """Traverse snapshot history with a stable repository-bound cursor."""
    name = f"{owner}/{repository}"
    before = decode_snapshot_cursor(cursor, name) if cursor is not None else None
    snapshots = store.history_before(name, limit=limit + 1, before=before)
    has_more = len(snapshots) > limit
    page = snapshots[:limit]
    return {
        "repository": name,
        "items": [snapshot.to_dict() for snapshot in page],
        "page_size": len(page),
        "has_more": has_more,
        "next_cursor": (
            encode_snapshot_cursor(name, page[-1].collected_at)
            if has_more and page
            else None
        ),
    }


@app.get("/github/{owner}/{repository}/snapshots/export")
def export_github_repository_snapshots(
    owner: str,
    repository: str,
    store: Annotated[SnapshotStore, Depends(snapshot_store_dependency)],
    limit: int = Query(default=365, ge=1, le=365),
) -> Response:
    """Download stored snapshot history without making a GitHub API request."""
    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(("collected_at", "repository", "stars", "forks", "open_issues",
                     "language", "archived", "default_branch"))
    for snapshot in store.history(f"{owner}/{repository}", limit=limit):
        writer.writerow((snapshot.collected_at, spreadsheet_safe_text(snapshot.repository),
                         snapshot.stars, snapshot.forks, snapshot.open_issues,
                         spreadsheet_safe_text(snapshot.language), snapshot.archived,
                         spreadsheet_safe_text(snapshot.default_branch)))

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


@app.get("/github/snapshots/freshness")
def github_snapshot_portfolio_freshness(
    store: Annotated[SnapshotStore, Depends(snapshot_store_dependency)],
    max_age_hours: float = Query(default=24.0, gt=0, le=8760),
) -> dict:
    """Report whether each repository's latest snapshot meets a freshness SLA."""
    return portfolio_snapshot_freshness(
        store.latest(),
        max_age_hours=max_age_hours,
        now=utc_now(),
    )


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


@app.get("/github/snapshots/report.csv")
def export_github_snapshot_portfolio_report(
    store: Annotated[SnapshotStore, Depends(snapshot_store_dependency)],
    trend_limit: int = Query(default=30, ge=2, le=365),
) -> Response:
    """Export current state, latest deltas, and growth velocity in one report."""
    histories = store.latest_history(limit_per_repository=trend_limit)
    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow((
        "repository", "status", "collected_at", "language", "archived",
        "stars", "forks", "open_issues", "stars_change", "forks_change",
        "open_issues_change", "stars_per_day", "forks_per_day",
        "open_issues_per_day",
    ))

    for repository, history in histories.items():
        current = history[0]
        trend = repository_trend(history, repository)
        if len(history) >= 2:
            changes = snapshot_changes(current, history[1])
            change_values: tuple[int | str, ...] = (
                int(changes["stars"]),
                int(changes["forks"]),
                int(changes["open_issues"]),
            )
            velocity = trend["per_day"]
            velocity_values = (
                velocity["stars"],
                velocity["forks"],
                velocity["open_issues"],
            )
        else:
            change_values = ("", "", "")
            velocity_values = ("", "", "")

        writer.writerow((
            spreadsheet_safe_text(repository),
            trend["status"],
            current.collected_at,
            spreadsheet_safe_text(current.language),
            current.archived,
            current.stars,
            current.forks,
            current.open_issues,
            *change_values,
            *velocity_values,
        ))

    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                'attachment; filename="devpulse-portfolio-report.csv"'
            )
        },
    )


def portfolio_alerts(
    histories: dict[str, list[RepositorySnapshot]],
    issue_spike_threshold: int,
) -> dict:
    """Build a deterministic alert summary from recent portfolio history."""
    alerts: list[dict] = []
    insufficient_data = []

    for repository, history in histories.items():
        if len(history) < 2:
            insufficient_data.append(repository)
            continue
        current, previous = history[:2]
        changes = snapshot_changes(current, previous)
        if changes["archived_changed"]:
            alerts.append({
                "repository": repository,
                "severity": "critical" if current.archived else "info",
                "type": "repository_archived" if current.archived else "repository_reactivated",
                "previous": previous.archived,
                "current": current.archived,
                "detected_at": current.collected_at,
            })
        if changes["default_branch_changed"]:
            alerts.append({
                "repository": repository,
                "severity": "warning",
                "type": "default_branch_changed",
                "previous": previous.default_branch,
                "current": current.default_branch,
                "detected_at": current.collected_at,
            })
        if changes["stars"] < 0:
            alerts.append({
                "repository": repository,
                "severity": "warning",
                "type": "stars_lost",
                "change": changes["stars"],
                "current": current.stars,
                "detected_at": current.collected_at,
            })
        if changes["open_issues"] >= issue_spike_threshold:
            alerts.append({
                "repository": repository,
                "severity": (
                    "critical"
                    if changes["open_issues"] >= issue_spike_threshold * 2
                    else "warning"
                ),
                "type": "open_issue_spike",
                "change": changes["open_issues"],
                "current": current.open_issues,
                "detected_at": current.collected_at,
            })

    severity_rank = {"critical": 0, "warning": 1, "info": 2}
    alerts.sort(key=lambda alert: (
        severity_rank[alert["severity"]],
        alert["repository"].casefold(),
        alert["type"],
    ))
    return {
        "repositories_tracked": len(histories),
        "repositories_evaluated": len(histories) - len(insufficient_data),
        "insufficient_data_repositories": insufficient_data,
        "issue_spike_threshold": issue_spike_threshold,
        "alert_count": len(alerts),
        "severity_counts": {
            severity: sum(alert["severity"] == severity for alert in alerts)
            for severity in ("critical", "warning", "info")
        },
        "alerts": alerts,
    }


@app.get("/github/snapshots/alerts")
def github_snapshot_portfolio_alerts(
    request: Request,
    store: Annotated[SnapshotStore, Depends(snapshot_store_dependency)],
    issue_spike_threshold: int = Query(default=10, ge=1, le=10_000),
) -> Response:
    """Identify actionable changes across the latest repository snapshots."""
    payload = portfolio_alerts(
        store.latest_history(limit_per_repository=2),
        issue_spike_threshold,
    )
    return conditional_json_response(request, payload)


@app.get("/github/snapshots/gate")
def github_snapshot_portfolio_gate(
    store: Annotated[SnapshotStore, Depends(snapshot_store_dependency)],
    max_age_hours: float = Query(default=24.0, gt=0, le=8760),
    max_stale_repositories: int = Query(default=0, ge=0, le=10_000),
    max_critical_alerts: int = Query(default=0, ge=0, le=10_000),
    max_warning_alerts: int = Query(default=0, ge=0, le=10_000),
    issue_spike_threshold: int = Query(default=10, ge=1, le=10_000),
    enforce_http: bool = Query(default=False),
) -> Response:
    """Evaluate stored portfolio state against a deployment safety policy."""
    latest = store.latest()
    freshness = portfolio_snapshot_freshness(latest, max_age_hours, utc_now())
    alerts = portfolio_alerts(
        store.latest_history(limit_per_repository=2),
        issue_spike_threshold,
    )
    checks = {
        "data_available": len(latest) > 0,
        "freshness_budget_met": (
            freshness["stale_repositories"] <= max_stale_repositories
        ),
        "critical_alert_budget_met": (
            alerts["severity_counts"]["critical"] <= max_critical_alerts
        ),
        "warning_alert_budget_met": (
            alerts["severity_counts"]["warning"] <= max_warning_alerts
        ),
    }
    payload = {
        "status": "pass" if all(checks.values()) else "fail",
        "evaluated_at": freshness["evaluated_at"],
        "checks": checks,
        "policy": {
            "max_age_hours": max_age_hours,
            "max_stale_repositories": max_stale_repositories,
            "max_critical_alerts": max_critical_alerts,
            "max_warning_alerts": max_warning_alerts,
            "issue_spike_threshold": issue_spike_threshold,
        },
        "observed": {
            "repositories_tracked": len(latest),
            "stale_repositories": freshness["stale_repositories"],
            "critical_alerts": alerts["severity_counts"]["critical"],
            "warning_alerts": alerts["severity_counts"]["warning"],
            "insufficient_data_repositories": len(
                alerts["insufficient_data_repositories"]
            ),
        },
        "failing_checks": [
            name for name, passed in checks.items() if not passed
        ],
    }
    gate_passed = all(checks.values())
    return JSONResponse(
        status_code=200 if gate_passed or not enforce_http else 503,
        content=payload,
        headers={"X-DevPulse-Gate": "pass" if gate_passed else "fail"},
    )


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
