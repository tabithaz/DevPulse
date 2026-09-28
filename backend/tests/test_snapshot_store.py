from pathlib import Path
import csv
from io import StringIO
import sqlite3

from fastapi.testclient import TestClient
import pytest

from app.github_client import (
    GitHubNotFoundError,
    RepositorySnapshot,
    github_client_dependency,
)
from app.main import app
from app.snapshot_store import SnapshotStore, snapshot_store_dependency

client = TestClient(app)


def snapshot(
    collected_at: str,
    stars: int = 10,
    forks: int = 3,
    open_issues: int = 2,
    repository: str = "octocat/hello-world",
    language: str | None = "Python",
    archived: bool = False,
) -> RepositorySnapshot:
    return RepositorySnapshot(
        repository=repository,
        description="A test repository",
        default_branch="main",
        language=language,
        stars=stars,
        forks=forks,
        open_issues=open_issues,
        archived=archived,
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


def test_snapshot_store_batch_is_atomic(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "snapshots.db")
    duplicate = snapshot("2026-09-21T12:00:00+00:00")

    with pytest.raises(sqlite3.IntegrityError):
        store.save_many([duplicate, duplicate])

    assert store.history("octocat/hello-world") == []


def test_snapshot_retention_prunes_each_repository_independently(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "snapshots.db", retention_per_repository=2)
    store.save(snapshot("2026-09-21T12:00:00+00:00", stars=10))
    store.save(snapshot("2026-09-21T14:00:00+00:00", stars=12))
    store.save(snapshot("2026-09-21T16:00:00+00:00", stars=14))
    store.save(snapshot(
        "2026-09-21T13:00:00+00:00",
        repository="octocat/another-repo",
        stars=4,
    ))

    assert [item.stars for item in store.history("octocat/hello-world")] == [14, 12]
    assert [item.stars for item in store.history("octocat/another-repo")] == [4]


def test_snapshot_retention_configuration_is_validated(tmp_path: Path, monkeypatch) -> None:
    with pytest.raises(ValueError, match="retention_per_repository"):
        SnapshotStore(tmp_path / "snapshots.db", retention_per_repository=0)

    monkeypatch.setenv("DEVPULSE_DB_PATH", str(tmp_path / "environment.db"))
    monkeypatch.setenv("DEVPULSE_SNAPSHOT_RETENTION", "2")
    assert SnapshotStore.from_environment().retention_per_repository == 2

    monkeypatch.setenv("DEVPULSE_SNAPSHOT_RETENTION", "unlimited")
    with pytest.raises(ValueError, match="positive integer"):
        SnapshotStore.from_environment()


def test_snapshot_store_returns_latest_snapshot_per_repository(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "snapshots.db")
    store.save(snapshot("2026-09-21T12:00:00+00:00", stars=10))
    store.save(snapshot("2026-09-21T14:00:00+00:00", stars=12))
    store.save(snapshot(
        "2026-09-21T13:00:00+00:00",
        repository="octocat/another-repo",
        stars=4,
    ))

    latest = store.latest()

    assert [item.repository for item in latest] == [
        "octocat/another-repo",
        "octocat/hello-world",
    ]
    assert [item.stars for item in latest] == [4, 12]


def test_snapshot_store_returns_bounded_history_for_every_repository(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "snapshots.db")
    for hour, stars in ((12, 10), (14, 12), (16, 15)):
        store.save(snapshot(f"2026-09-21T{hour}:00:00+00:00", stars=stars))
    store.save(snapshot(
        "2026-09-21T13:00:00+00:00",
        repository="octocat/another-repo",
        stars=4,
    ))

    histories = store.latest_history(limit_per_repository=2)

    assert list(histories) == ["octocat/another-repo", "octocat/hello-world"]
    assert [item.stars for item in histories["octocat/hello-world"]] == [15, 12]
    assert [item.stars for item in histories["octocat/another-repo"]] == [4]


class StubGitHubClient:
    def repository_snapshot(self, owner: str, repository: str) -> RepositorySnapshot:
        assert (owner, repository) == ("octocat", "hello-world")
        return snapshot("2026-09-21T14:00:00+00:00", stars=12)


class BatchGitHubClient:
    def repository_snapshot(self, owner: str, repository: str) -> RepositorySnapshot:
        if repository == "missing":
            raise GitHubNotFoundError(f"repository {owner}/{repository} was not found")
        return snapshot(
            "2026-09-21T14:00:00+00:00",
            repository=f"{owner}/{repository}",
            stars=12 if repository == "hello-world" else 7,
        )


class CountingGitHubClient:
    def __init__(self) -> None:
        self.calls = 0

    def repository_snapshot(self, owner: str, repository: str) -> RepositorySnapshot:
        self.calls += 1
        return snapshot(
            f"2026-09-21T{13 + self.calls}:00:00+00:00",
            repository=f"{owner}/{repository}",
            stars=10 + self.calls,
        )


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


def test_single_collection_idempotency_survives_store_restart(tmp_path: Path) -> None:
    database_path = tmp_path / "snapshots.db"
    github = CountingGitHubClient()
    store = SnapshotStore(database_path)
    app.dependency_overrides[github_client_dependency] = lambda: github
    app.dependency_overrides[snapshot_store_dependency] = lambda: store
    try:
        first = client.post(
            "/github/octocat/hello-world/snapshots",
            headers={"Idempotency-Key": "collection-42"},
        )
        store = SnapshotStore(database_path)
        replay = client.post(
            "/github/octocat/hello-world/snapshots",
            headers={"Idempotency-Key": "collection-42"},
        )
    finally:
        app.dependency_overrides.clear()

    assert first.status_code == replay.status_code == 201
    assert first.json() == replay.json()
    assert first.headers["idempotency-replayed"] == "false"
    assert replay.headers["idempotency-replayed"] == "true"
    assert github.calls == 1
    assert len(store.history("octocat/hello-world")) == 1


def test_collection_rejects_conflicting_and_malformed_idempotency_keys(
    tmp_path: Path,
) -> None:
    store = SnapshotStore(tmp_path / "snapshots.db")
    github = CountingGitHubClient()
    app.dependency_overrides[github_client_dependency] = lambda: github
    app.dependency_overrides[snapshot_store_dependency] = lambda: store
    try:
        first = client.post(
            "/github/octocat/hello-world/snapshots",
            headers={"Idempotency-Key": "collection-42"},
        )
        conflict = client.post(
            "/github/octocat/another-repo/snapshots",
            headers={"Idempotency-Key": "collection-42"},
        )
        malformed = client.post(
            "/github/octocat/hello-world/snapshots",
            headers={"Idempotency-Key": "contains spaces"},
        )
    finally:
        app.dependency_overrides.clear()

    assert first.status_code == 201
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == (
        "idempotency key was already used for a different request"
    )
    assert malformed.status_code == 422
    assert github.calls == 1


def test_batch_collection_replays_without_refetching_or_rewriting(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "snapshots.db")
    github = CountingGitHubClient()
    app.dependency_overrides[github_client_dependency] = lambda: github
    app.dependency_overrides[snapshot_store_dependency] = lambda: store
    payload = {
        "repositories": [
            {"owner": "octocat", "repository": "hello-world"},
            {"owner": "octocat", "repository": "analytics"},
        ]
    }
    try:
        first = client.post(
            "/github/snapshots/collect",
            json=payload,
            headers={"Idempotency-Key": "portfolio-2026-09-28"},
        )
        replay = client.post(
            "/github/snapshots/collect",
            json=payload,
            headers={"Idempotency-Key": "portfolio-2026-09-28"},
        )
    finally:
        app.dependency_overrides.clear()

    assert first.status_code == replay.status_code == 201
    assert first.json() == replay.json()
    assert replay.headers["idempotency-replayed"] == "true"
    assert github.calls == 2
    assert len(store.latest()) == 2


def test_batch_collection_persists_all_repositories(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "snapshots.db")
    app.dependency_overrides[github_client_dependency] = lambda: BatchGitHubClient()
    app.dependency_overrides[snapshot_store_dependency] = lambda: store
    try:
        response = client.post("/github/snapshots/collect", json={
            "repositories": [
                {"owner": "octocat", "repository": "hello-world"},
                {"owner": "octocat", "repository": "analytics"},
            ]
        })
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    assert response.json()["collected"] == 2
    assert len(store.history("octocat/hello-world")) == 1
    assert len(store.history("octocat/analytics")) == 1


def test_batch_collection_rejects_duplicates_and_is_atomic_on_upstream_failure(
    tmp_path: Path,
) -> None:
    store = SnapshotStore(tmp_path / "snapshots.db")
    app.dependency_overrides[github_client_dependency] = lambda: BatchGitHubClient()
    app.dependency_overrides[snapshot_store_dependency] = lambda: store
    try:
        duplicate = client.post("/github/snapshots/collect", json={
            "repositories": [
                {"owner": "octocat", "repository": "hello-world"},
                {"owner": "OCTOCAT", "repository": "HELLO-WORLD"},
            ]
        })
        failed = client.post("/github/snapshots/collect", json={
            "repositories": [
                {"owner": "octocat", "repository": "hello-world"},
                {"owner": "octocat", "repository": "missing"},
            ]
        })
        oversized = client.post("/github/snapshots/collect", json={
            "repositories": [
                {"owner": "octocat", "repository": f"repository-{index}"}
                for index in range(26)
            ]
        })
        malformed = client.post("/github/snapshots/collect", json={
            "repositories": [{"owner": "octocat/team", "repository": "repo"}]
        })
    finally:
        app.dependency_overrides.clear()

    assert duplicate.status_code == 422
    assert failed.status_code == 404
    assert oversized.status_code == 422
    assert malformed.status_code == 422
    assert store.latest() == []


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


def test_snapshot_export_is_bounded_ordered_and_spreadsheet_safe(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "snapshots.db")
    store.save(snapshot("2026-09-21T12:00:00+00:00", stars=10))
    store.save(snapshot("2026-09-21T14:00:00+00:00", stars=12,
                        language='=HYPERLINK("https://example.com")'))
    app.dependency_overrides[snapshot_store_dependency] = lambda: store
    try:
        response = client.get("/github/octocat/hello-world/snapshots/export")
        limited = client.get("/github/octocat/hello-world/snapshots/export?limit=1")
        invalid = client.get("/github/octocat/hello-world/snapshots/export?limit=0")
        empty = client.get("/github/octocat/missing/snapshots/export")
    finally:
        app.dependency_overrides.clear()

    rows = list(csv.DictReader(StringIO(response.text)))
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"] == 'attachment; filename="devpulse-snapshots.csv"'
    assert [row["stars"] for row in rows] == ["12", "10"]
    assert rows[0]["language"].startswith("'=HYPERLINK")
    assert len(list(csv.DictReader(StringIO(limited.text)))) == 1
    assert invalid.status_code == 422
    assert len(list(csv.DictReader(StringIO(empty.text)))) == 0


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


def test_snapshot_trend_reports_velocity_and_volatility(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "snapshots.db")
    for day, stars, forks, issues in (
        (21, 10, 2, 8),
        (22, 13, 3, 7),
        (23, 12, 5, 9),
        (24, 18, 5, 6),
    ):
        store.save(snapshot(
            f"2026-09-{day}T12:00:00+00:00",
            stars=stars,
            forks=forks,
            open_issues=issues,
        ))
    app.dependency_overrides[snapshot_store_dependency] = lambda: store
    try:
        response = client.get(
            "/github/octocat/hello-world/snapshots/trend",
            params={"limit": 4},
        )
        cached = client.get(
            "/github/octocat/hello-world/snapshots/trend?limit=4",
            headers={"If-None-Match": response.headers["etag"]},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "repository": "octocat/hello-world",
        "status": "ready",
        "snapshots_analyzed": 4,
        "window": {
            "started_at": "2026-09-21T12:00:00+00:00",
            "ended_at": "2026-09-24T12:00:00+00:00",
            "elapsed_days": 3.0,
        },
        "net_changes": {"stars": 8, "forks": 3, "open_issues": -2},
        "per_day": {"stars": 2.667, "forks": 1.0, "open_issues": -0.667},
        "change_volatility": {
            "stars": 2.867,
            "forks": 0.816,
            "open_issues": 2.055,
        },
    }
    assert cached.status_code == 304
    assert cached.content == b""


def test_snapshot_trend_handles_empty_single_and_invalid_windows(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "snapshots.db")
    app.dependency_overrides[snapshot_store_dependency] = lambda: store
    try:
        empty = client.get("/github/octocat/hello-world/snapshots/trend")
        store.save(snapshot("2026-09-21T12:00:00+00:00"))
        single = client.get("/github/octocat/hello-world/snapshots/trend")
        invalid = client.get(
            "/github/octocat/hello-world/snapshots/trend",
            params={"limit": 1},
        )
    finally:
        app.dependency_overrides.clear()

    assert empty.json()["status"] == "no_data"
    assert empty.json()["snapshots_analyzed"] == 0
    assert single.json()["status"] == "insufficient_data"
    assert single.json()["snapshots_analyzed"] == 1
    assert invalid.status_code == 422


def test_snapshot_portfolio_summary_aggregates_latest_snapshots(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "snapshots.db")
    store.save(snapshot("2026-09-21T12:00:00+00:00", stars=10))
    store.save(snapshot("2026-09-21T14:00:00+00:00", stars=12))
    store.save(snapshot(
        "2026-09-21T13:00:00+00:00",
        repository="octocat/archived",
        language=None,
        archived=True,
        stars=5,
    ))
    app.dependency_overrides[snapshot_store_dependency] = lambda: store
    try:
        response = client.get("/github/snapshots/summary")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "repositories_tracked": 2,
        "active_repositories": 1,
        "archived_repositories": 1,
        "total_stars": 17,
        "total_forks": 6,
        "total_open_issues": 4,
        "languages": {"Python": 1, "Unknown": 1},
        "repositories": [
            snapshot(
                "2026-09-21T13:00:00+00:00",
                repository="octocat/archived",
                language=None,
                archived=True,
                stars=5,
            ).to_dict(),
            snapshot("2026-09-21T14:00:00+00:00", stars=12).to_dict(),
        ],
    }


def test_snapshot_portfolio_summary_handles_empty_store(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "snapshots.db")
    app.dependency_overrides[snapshot_store_dependency] = lambda: store
    try:
        response = client.get("/github/snapshots/summary")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["repositories_tracked"] == 0
    assert response.json()["repositories"] == []


def test_snapshot_portfolio_summary_supports_etag_revalidation(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "snapshots.db")
    store.save(snapshot("2026-09-21T12:00:00+00:00", stars=10))
    app.dependency_overrides[snapshot_store_dependency] = lambda: store
    try:
        first = client.get("/github/snapshots/summary")
        unchanged = client.get(
            "/github/snapshots/summary",
            headers={"If-None-Match": first.headers["etag"]},
        )
        weak_match = client.get(
            "/github/snapshots/summary",
            headers={"If-None-Match": f'W/{first.headers["etag"]}'},
        )
        store.save(snapshot("2026-09-21T14:00:00+00:00", stars=12))
        changed = client.get(
            "/github/snapshots/summary",
            headers={"If-None-Match": first.headers["etag"]},
        )
    finally:
        app.dependency_overrides.clear()

    assert first.status_code == 200
    assert first.headers["cache-control"] == "private, max-age=0, must-revalidate"
    assert unchanged.status_code == 304
    assert unchanged.content == b""
    assert unchanged.headers["etag"] == first.headers["etag"]
    assert weak_match.status_code == 304
    assert changed.status_code == 200
    assert changed.json()["total_stars"] == 12
    assert changed.headers["etag"] != first.headers["etag"]


def test_snapshot_portfolio_delta_aggregates_latest_changes(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "snapshots.db")
    store.save(snapshot("2026-09-21T12:00:00+00:00", stars=10))
    store.save(snapshot("2026-09-21T14:00:00+00:00", stars=13))
    store.save(snapshot(
        "2026-09-21T13:00:00+00:00",
        repository="octocat/new-repo",
        stars=4,
    ))
    app.dependency_overrides[snapshot_store_dependency] = lambda: store
    try:
        response = client.get("/github/snapshots/delta")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["repositories_tracked"] == 2
    assert response.json()["comparable_repositories"] == 1
    assert response.json()["repositories_gaining_stars"] == 1
    assert response.json()["repositories_losing_stars"] == 0
    assert response.json()["total_changes"] == {
        "stars": 3, "forks": 0, "open_issues": 0,
    }
    assert response.json()["repositories"][1]["status"] == "insufficient_data"


def test_snapshot_portfolio_delta_handles_empty_store_and_etag(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "snapshots.db")
    app.dependency_overrides[snapshot_store_dependency] = lambda: store
    try:
        response = client.get("/github/snapshots/delta")
        unchanged = client.get(
            "/github/snapshots/delta",
            headers={"If-None-Match": response.headers["etag"]},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["repositories_tracked"] == 0
    assert response.json()["total_changes"] == {
        "stars": 0, "forks": 0, "open_issues": 0,
    }
    assert unchanged.status_code == 304
