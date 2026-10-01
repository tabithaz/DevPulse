from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from app.github_client import RepositorySnapshot, github_client_dependency
from app.main import app
from app.snapshot_store import SnapshotStore, snapshot_store_dependency


client = TestClient(app)


class CountingGitHubClient:
    def __init__(self) -> None:
        self.calls = 0

    def repository_snapshot(self, owner: str, repository: str) -> RepositorySnapshot:
        self.calls += 1
        return RepositorySnapshot(
            repository=f"{owner}/{repository}",
            description="Protected collection",
            default_branch="main",
            language="Python",
            stars=10,
            forks=2,
            open_issues=1,
            archived=False,
            created_at="2025-01-01T00:00:00Z",
            pushed_at="2026-10-01T12:00:00Z",
            collected_at="2026-10-01T12:01:00+00:00",
        )


@pytest.fixture
def protected_collection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    github = CountingGitHubClient()
    store = SnapshotStore(tmp_path / "protected.db")
    app.dependency_overrides[github_client_dependency] = lambda: github
    app.dependency_overrides[snapshot_store_dependency] = lambda: store
    monkeypatch.setenv("DEVPULSE_API_KEY", "portfolio-secret")
    try:
        yield github, store
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/github/tabithaz/DevPulse/snapshots", None),
        (
            "/github/snapshots/collect",
            {"repositories": [{"owner": "tabithaz", "repository": "DevPulse"}]},
        ),
    ],
)
def test_manual_collection_requires_valid_api_key(
    path: str,
    payload: dict | None,
    protected_collection,
) -> None:
    github, store = protected_collection

    missing = client.post(path, json=payload)
    wrong = client.post(path, json=payload, headers={"X-API-Key": "wrong"})

    assert missing.status_code == wrong.status_code == 401
    assert missing.json() == {"detail": "valid X-API-Key required"}
    assert missing.headers["www-authenticate"] == "ApiKey"
    assert github.calls == 0
    assert store.latest() == []
    assert store.collection_runs() == []


def test_valid_api_key_allows_manual_collection(protected_collection) -> None:
    github, store = protected_collection

    response = client.post(
        "/github/tabithaz/DevPulse/snapshots",
        headers={"X-API-Key": "portfolio-secret"},
    )

    assert response.status_code == 201
    assert github.calls == 1
    assert len(store.latest()) == 1


def test_read_endpoints_and_webhook_route_are_not_intercepted(
    protected_collection,
) -> None:
    read = client.get("/github/snapshots/summary")
    webhook = client.post("/github/webhooks", content=b"{}")

    assert read.status_code == 200
    assert webhook.status_code != 401
