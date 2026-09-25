from pathlib import Path

from fastapi.testclient import TestClient

from app.github_client import RepositorySnapshot, github_client_dependency
from app.main import app
from app.snapshot_store import SnapshotStore, snapshot_store_dependency

client = TestClient(app)


def snapshot(collected_at: str, stars: int = 10) -> RepositorySnapshot:
    return RepositorySnapshot(
        repository="octocat/hello-world",
        description="A test repository",
        default_branch="main",
        language="Python",
        stars=stars,
        forks=3,
        open_issues=2,
        archived=False,
        created_at="2024-01-01T00:00:00Z",
        pushed_at="2026-09-21T12:00:00Z",
        collected_at=collected_at,
    )


def test_snapshot_store_persists_ordered_history(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "snapshots.db")
    store.save(snapshot("2026-09-21T12:00:00+00:00", stars=10))
    store.save(snapshot("2026-09-21T14:00:00+00:00", stars=12))

    history = store.history("octocat/hello-world")

    assert [item.stars for item in history] == [12, 10]
    assert history[0].archived is False


def test_snapshot_store_limits_history(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "snapshots.db")
    store.save(snapshot("2026-09-21T12:00:00+00:00"))
    store.save(snapshot("2026-09-21T14:00:00+00:00"))

    assert len(store.history("octocat/hello-world", limit=1)) == 1
    assert store.history("octocat/missing") == []


class StubGitHubClient:
    def repository_snapshot(self, owner: str, repository: str) -> RepositorySnapshot:
        assert (owner, repository) == ("octocat", "hello-world")
        return snapshot("2026-09-21T14:00:00+00:00", stars=12)


def test_collect_and_read_snapshot_history(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "snapshots.db")
    app.dependency_overrides[github_client_dependency] = lambda: StubGitHubClient()
    app.dependency_overrides[snapshot_store_dependency] = lambda: store
    try:
        collected = client.post("/github/octocat/hello-world/snapshots")
        history = client.get("/github/octocat/hello-world/snapshots")
    finally:
        app.dependency_overrides.clear()

    assert collected.status_code == 201
    assert collected.json()["stars"] == 12
    assert history.status_code == 200
    assert history.json() == [collected.json()]


def test_snapshot_history_validates_limit(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "snapshots.db")
    app.dependency_overrides[snapshot_store_dependency] = lambda: store
    try:
        response = client.get(
            "/github/octocat/hello-world/snapshots",
            params={"limit": 0},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422


def test_snapshot_delta_reports_empty_and_single_history(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "snapshots.db")
    app.dependency_overrides[snapshot_store_dependency] = lambda: store
    try:
        empty = client.get("/github/octocat/hello-world/snapshots/delta")
        store.save(snapshot("2026-09-21T12:00:00+00:00", stars=10))
        single = client.get("/github/octocat/hello-world/snapshots/delta")
    finally:
        app.dependency_overrides.clear()

    assert empty.status_code == 200
    assert empty.json()["status"] == "no_data"
    assert empty.json()["changes"] is None
    assert single.json()["status"] == "insufficient_data"
    assert single.json()["current"]["stars"] == 10


def test_snapshot_delta_uses_latest_two_snapshots(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "snapshots.db")
    store.save(snapshot("2026-09-21T12:00:00+00:00", stars=10))
    store.save(snapshot("2026-09-21T14:00:00+00:00", stars=12))
    store.save(snapshot("2026-09-21T16:00:00+00:00", stars=9))
    app.dependency_overrides[snapshot_store_dependency] = lambda: store
    try:
        result = client.get("/github/octocat/hello-world/snapshots/delta")
    finally:
        app.dependency_overrides.clear()

    assert result.status_code == 200
    assert result.json()["status"] == "ready"
    assert result.json()["current"]["stars"] == 9
    assert result.json()["previous_collected_at"] == "2026-09-21T14:00:00+00:00"
    assert result.json()["changes"] == {
        "stars": -3, "forks": 0, "open_issues": 0,
        "archived_changed": False, "default_branch_changed": False,
    }
