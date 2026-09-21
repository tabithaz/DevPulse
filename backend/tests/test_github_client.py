import httpx
import pytest
from fastapi.testclient import TestClient

from app.github_client import (
    GitHubClient,
    GitHubNotFoundError,
    GitHubRateLimitError,
    GitHubServiceError,
    RepositorySnapshot,
    github_client_dependency,
)
from app.main import app

client = TestClient(app)


def repository_payload() -> dict:
    return {
        "full_name": "octocat/hello-world",
        "description": "A test repository",
        "default_branch": "main",
        "language": "Python",
        "stargazers_count": 12,
        "forks_count": 3,
        "open_issues_count": 2,
        "archived": False,
        "created_at": "2024-01-01T00:00:00Z",
        "pushed_at": "2026-09-21T12:00:00Z",
    }


def test_github_client_builds_repository_snapshot() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=repository_payload(), request=request)
    )

    with GitHubClient(token="test-token", transport=transport) as github:
        snapshot = github.repository_snapshot("octocat", "hello-world")

    assert snapshot.repository == "octocat/hello-world"
    assert snapshot.stars == 12
    assert snapshot.forks == 3
    assert snapshot.open_issues == 2
    assert snapshot.collected_at.endswith("+00:00")


def test_github_client_sends_token_without_returning_it() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-token"
        return httpx.Response(200, json=repository_payload(), request=request)

    with GitHubClient(token="test-token", transport=httpx.MockTransport(handler)) as github:
        result = github.repository_snapshot("octocat", "hello-world").to_dict()

    assert "token" not in result


def test_github_client_classifies_not_found_and_rate_limit_errors() -> None:
    not_found = httpx.MockTransport(
        lambda request: httpx.Response(404, request=request)
    )
    limited = httpx.MockTransport(
        lambda request: httpx.Response(
            403,
            headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1789999999"},
            request=request,
        )
    )

    with GitHubClient(transport=not_found) as github:
        with pytest.raises(GitHubNotFoundError):
            github.repository_snapshot("missing", "repository")

    with GitHubClient(transport=limited) as github:
        with pytest.raises(GitHubRateLimitError) as error:
            github.repository_snapshot("octocat", "hello-world")

    assert error.value.reset_at == "1789999999"


def test_github_client_rejects_malformed_payload() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, json={"full_name": "incomplete"}, request=request
        )
    )

    with GitHubClient(transport=transport) as github:
        with pytest.raises(GitHubServiceError, match="invalid repository payload"):
            github.repository_snapshot("octocat", "hello-world")


class StubGitHubClient:
    def repository_snapshot(self, owner: str, repository: str) -> RepositorySnapshot:
        assert (owner, repository) == ("octocat", "hello-world")
        return RepositorySnapshot(
            repository="octocat/hello-world",
            description="A test repository",
            default_branch="main",
            language="Python",
            stars=12,
            forks=3,
            open_issues=2,
            archived=False,
            created_at="2024-01-01T00:00:00Z",
            pushed_at="2026-09-21T12:00:00Z",
            collected_at="2026-09-21T14:00:00+00:00",
        )


def test_github_snapshot_endpoint_returns_normalized_metadata() -> None:
    app.dependency_overrides[github_client_dependency] = lambda: StubGitHubClient()
    try:
        response = client.get("/github/octocat/hello-world/snapshot")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["repository"] == "octocat/hello-world"
    assert response.json()["stars"] == 12
    assert response.json()["collected_at"] == "2026-09-21T14:00:00+00:00"


def test_github_snapshot_endpoint_translates_not_found() -> None:
    class MissingClient:
        def repository_snapshot(self, owner: str, repository: str) -> RepositorySnapshot:
            raise GitHubNotFoundError("repository was not found")

    app.dependency_overrides[github_client_dependency] = lambda: MissingClient()
    try:
        response = client.get("/github/missing/repository/snapshot")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


def test_github_snapshot_endpoint_translates_rate_limits() -> None:
    class LimitedClient:
        def repository_snapshot(self, owner: str, repository: str) -> RepositorySnapshot:
            raise GitHubRateLimitError("1789999999")

    app.dependency_overrides[github_client_dependency] = lambda: LimitedClient()
    try:
        response = client.get("/github/octocat/hello-world/snapshot")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 429
    assert "1789999999" in response.json()["detail"]


def test_github_snapshot_endpoint_translates_service_errors() -> None:
    class FailingClient:
        def repository_snapshot(self, owner: str, repository: str) -> RepositorySnapshot:
            raise GitHubServiceError("GitHub API is unavailable")

    app.dependency_overrides[github_client_dependency] = lambda: FailingClient()
    try:
        response = client.get("/github/octocat/hello-world/snapshot")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 502
