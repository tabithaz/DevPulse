import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Iterator

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


class GitHubClient:
    def __init__(
        self,
        token: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
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

    @classmethod
    def from_environment(cls) -> "GitHubClient":
        return cls(token=os.getenv("GITHUB_TOKEN"))

    def __enter__(self) -> "GitHubClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def repository_snapshot(self, owner: str, repository: str) -> RepositorySnapshot:
        try:
            response = self._client.get(f"/repos/{owner}/{repository}")
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise GitHubServiceError("GitHub API is unavailable") from exc

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
