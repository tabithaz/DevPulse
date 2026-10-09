import math
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Callable, Iterator

import httpx


class GitHubClientError(RuntimeError):
    """Base error for GitHub API failures."""


class GitHubNotFoundError(GitHubClientError):
    pass


class GitHubRateLimitError(GitHubClientError):
    def __init__(self, reset_at: str | None = None) -> None:
        super().__init__("GitHub API rate limit exceeded")
        self.reset_at = reset_at


class GitHubServiceError(GitHubClientError):
    pass


@dataclass(frozen=True)
class RepositorySnapshot:
    repository: str
    description: str | None
    default_branch: str
    language: str | None
    stars: int
    forks: int
    open_issues: int
    archived: bool
    created_at: str
    pushed_at: str | None
    collected_at: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class GitHubRateLimit:
    resource: str
    limit: int
    remaining: int
    used: int
    remaining_percent: float
    reset_at: str
    reset_in_seconds: int
    status: str

    def to_dict(self) -> dict:
        return asdict(self)


class GitHubClient:
    def __init__(
        self,
        token: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 10.0,
        max_attempts: int = 3,
        backoff_seconds: float = 0.25,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_attempts < 1 or max_attempts > 5:
            raise ValueError("max_attempts must be between 1 and 5")
        if (
            not math.isfinite(backoff_seconds)
            or backoff_seconds < 0
            or backoff_seconds > 60
        ):
            raise ValueError("backoff_seconds must be between 0 and 60")
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "DevPulse",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.Client(
            base_url="https://api.github.com",
            headers=headers,
            timeout=timeout_seconds,
            transport=transport,
        )
        self._max_attempts = max_attempts
        self._backoff_seconds = backoff_seconds
        self._sleep = sleep

    @classmethod
    def from_environment(cls) -> "GitHubClient":
        try:
            max_attempts = int(os.getenv("DEVPULSE_GITHUB_MAX_ATTEMPTS", "3"))
            backoff_seconds = float(
                os.getenv("DEVPULSE_GITHUB_BACKOFF_SECONDS", "0.25")
            )
            if (
                max_attempts < 1
                or max_attempts > 5
                or not math.isfinite(backoff_seconds)
                or backoff_seconds < 0
                or backoff_seconds > 60
            ):
                raise ValueError
        except ValueError:
            max_attempts = 3
            backoff_seconds = 0.25
        return cls(
            token=os.getenv("GITHUB_TOKEN"),
            max_attempts=max_attempts,
            backoff_seconds=backoff_seconds,
        )

    def __enter__(self) -> "GitHubClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _get(self, path: str) -> httpx.Response:
        """Retry bounded transient failures without replaying permanent errors."""
        for attempt in range(self._max_attempts):
            try:
                response = self._client.get(path)
            except httpx.TransportError:
                if attempt + 1 == self._max_attempts:
                    raise GitHubServiceError("GitHub API is unavailable")
            else:
                if response.status_code not in {500, 502, 503, 504}:
                    return response
                if attempt + 1 == self._max_attempts:
                    return response
            self._sleep(self._backoff_seconds * (2**attempt))
        raise AssertionError("retry loop must return or raise")

    def rate_limit(self) -> GitHubRateLimit:
        """Return the live quota for repository API requests."""
        response = self._get("/rate_limit")

        if response.is_error:
            raise GitHubServiceError(f"GitHub API returned status {response.status_code}")

        try:
            core = response.json()["resources"]["core"]
            limit = int(core["limit"])
            remaining = int(core["remaining"])
            used = int(core["used"])
            reset = int(core["reset"])
            if limit < 0 or remaining < 0 or used < 0 or remaining > limit:
                raise ValueError
            now = datetime.now(timezone.utc)
            remaining_percent = round((remaining / limit) * 100, 1) if limit else 0.0
            status = (
                "exhausted"
                if remaining == 0
                else "low"
                if remaining_percent <= 10
                else "healthy"
            )
            return GitHubRateLimit(
                resource="core",
                limit=limit,
                remaining=remaining,
                used=used,
                remaining_percent=remaining_percent,
                reset_at=datetime.fromtimestamp(reset, timezone.utc).isoformat(),
                reset_in_seconds=max(0, reset - int(now.timestamp())),
                status=status,
            )
        except (KeyError, TypeError, ValueError, OverflowError, OSError) as exc:
            raise GitHubServiceError("GitHub API returned an invalid rate limit payload") from exc

    def repository_snapshot(self, owner: str, repository: str) -> RepositorySnapshot:
        response = self._get(f"/repos/{owner}/{repository}")

        if response.status_code == 404:
            raise GitHubNotFoundError(f"repository {owner}/{repository} was not found")
        if response.status_code == 429 or (
            response.status_code == 403
            and response.headers.get("x-ratelimit-remaining") == "0"
        ):
            raise GitHubRateLimitError(response.headers.get("x-ratelimit-reset"))
        if response.is_error:
            raise GitHubServiceError(f"GitHub API returned status {response.status_code}")

        try:
            data = response.json()
            return RepositorySnapshot(
                repository=data["full_name"],
                description=data.get("description"),
                default_branch=data["default_branch"],
                language=data.get("language"),
                stars=data["stargazers_count"],
                forks=data["forks_count"],
                open_issues=data["open_issues_count"],
                archived=data["archived"],
                created_at=data["created_at"],
                pushed_at=data.get("pushed_at"),
                collected_at=datetime.now(timezone.utc).isoformat(),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise GitHubServiceError("GitHub API returned an invalid repository payload") from exc


def github_client_dependency() -> Iterator[GitHubClient]:
    with GitHubClient.from_environment() as client:
        yield client
