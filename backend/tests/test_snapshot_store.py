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
    default_branch: str = "main",
) -> RepositorySnapshot:
    return RepositorySnapshot(
        repository=repository,
        description="A test repository",
        default_branch=default_branch,
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
    assert store.collection_runs() == []


def test_collection_runs_are_bounded_and_newest_first(tmp_path: Path) -> None:
    store = SnapshotStore(
        tmp_path / "snapshots.db",
        collection_run_retention=2,
    )
    store.save(snapshot("2026-09-21T12:00:00+00:00"), trigger="api")
    store.save(snapshot(
        "2026-09-21T13:00:00+00:00",
        repository="octocat/analytics",
    ), trigger="webhook")
    store.save_many([
        snapshot("2026-09-21T14:00:00+00:00"),
        snapshot(
            "2026-09-21T14:00:00+00:00",
            repository="octocat/analytics",
        ),
    ], trigger="batch")

    runs = store.collection_runs()

    assert [run["trigger"] for run in runs] == ["batch", "webhook"]
    assert runs[0]["repository_count"] == 2
    assert runs[0]["repositories"] == [
        "octocat/analytics",
        "octocat/hello-world",
    ]
    assert runs[0]["recorded_at"]


def test_collection_run_configuration_and_trigger_are_validated(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="collection_run_retention"):
        SnapshotStore(tmp_path / "snapshots.db", collection_run_retention=0)

    store = SnapshotStore(tmp_path / "valid.db")
    with pytest.raises(ValueError, match="trigger"):
        store.save(snapshot("2026-09-21T12:00:00+00:00"), trigger="cron")

    assert store.history("octocat/hello-world") == []
    assert store.collection_runs() == []


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
    assert [run["trigger"] for run in store.collection_runs()] == ["api"]


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
        audit = client.get("/github/snapshots/collections")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    assert response.json()["collected"] == 2
    assert len(store.history("octocat/hello-world")) == 1
    assert len(store.history("octocat/analytics")) == 1
    assert audit.status_code == 200
    assert audit.json()[0]["trigger"] == "batch"
    assert audit.json()[0]["repository_count"] == 2
    assert audit.json()[0]["repositories"] == [
        "octocat/analytics",
        "octocat/hello-world",
    ]


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


def test_snapshot_history_page_uses_stable_keyset_cursor(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "snapshots.db")
    for hour, stars in ((12, 1), (13, 2), (14, 3), (15, 4), (16, 5)):
        store.save(snapshot(f"2026-09-21T{hour}:00:00+00:00", stars=stars))
    app.dependency_overrides[snapshot_store_dependency] = lambda: store
    try:
        first = client.get("/github/octocat/hello-world/snapshots/page?limit=2")
        store.save(snapshot("2026-09-21T17:00:00+00:00", stars=6))
        second = client.get(
            "/github/octocat/hello-world/snapshots/page",
            params={"limit": 2, "cursor": first.json()["next_cursor"]},
        )
        third = client.get(
            "/github/octocat/hello-world/snapshots/page",
            params={"limit": 2, "cursor": second.json()["next_cursor"]},
        )
    finally:
        app.dependency_overrides.clear()

    assert [item["stars"] for item in first.json()["items"]] == [5, 4]
    assert first.json()["page_size"] == 2
    assert first.json()["has_more"] is True
    assert [item["stars"] for item in second.json()["items"]] == [3, 2]
    assert second.json()["has_more"] is True
    assert [item["stars"] for item in third.json()["items"]] == [1]
    assert third.json()["page_size"] == 1
    assert third.json()["has_more"] is False
    assert third.json()["next_cursor"] is None


def test_snapshot_history_page_rejects_invalid_and_cross_repository_cursors(
    tmp_path: Path,
) -> None:
    store = SnapshotStore(tmp_path / "snapshots.db")
    store.save(snapshot("2026-09-21T12:00:00+00:00"))
    store.save(snapshot("2026-09-21T13:00:00+00:00"))
    app.dependency_overrides[snapshot_store_dependency] = lambda: store
    try:
        valid = client.get("/github/octocat/hello-world/snapshots/page?limit=1")
        invalid = client.get(
            "/github/octocat/hello-world/snapshots/page",
            params={"cursor": "not-a-valid-cursor"},
        )
        cross_repository = client.get(
            "/github/octocat/another-repo/snapshots/page",
            params={"cursor": valid.json()["next_cursor"]},
        )
        invalid_limit = client.get(
            "/github/octocat/hello-world/snapshots/page?limit=101"
        )
    finally:
        app.dependency_overrides.clear()

    assert invalid.status_code == 422
    assert invalid.json()["detail"] == "invalid snapshot cursor for repository"
    assert cross_repository.status_code == 422
    assert invalid_limit.status_code == 422


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


def test_snapshot_portfolio_trends_rank_growth_and_aggregate_velocity(
    tmp_path: Path,
) -> None:
    store = SnapshotStore(tmp_path / "snapshots.db")
    for repository, starting_stars, ending_stars, ending_forks in (
        ("octocat/steady", 10, 12, 4),
        ("octocat/fast", 20, 28, 7),
    ):
        store.save(snapshot(
            "2026-09-21T12:00:00+00:00",
            repository=repository,
            stars=starting_stars,
            forks=2,
            open_issues=5,
        ))
        store.save(snapshot(
            "2026-09-23T12:00:00+00:00",
            repository=repository,
            stars=ending_stars,
            forks=ending_forks,
            open_issues=3,
        ))
    store.save(snapshot(
        "2026-09-23T12:00:00+00:00",
        repository="octocat/new",
        stars=1,
    ))
    app.dependency_overrides[snapshot_store_dependency] = lambda: store
    try:
        response = client.get("/github/snapshots/trends?limit=30")
        cached = client.get(
            "/github/snapshots/trends?limit=30",
            headers={"If-None-Match": response.headers["etag"]},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["repositories_tracked"] == 3
    assert response.json()["comparable_repositories"] == 2
    assert response.json()["insufficient_data_repositories"] == 1
    assert response.json()["fastest_growing_repository"] == "octocat/fast"
    assert response.json()["total_net_changes"] == {
        "stars": 10, "forks": 7, "open_issues": -4,
    }
    assert response.json()["total_per_day"] == {
        "stars": 5.0, "forks": 3.5, "open_issues": -2.0,
    }
    assert [
        item["repository"] for item in response.json()["repositories"]
    ] == ["octocat/fast", "octocat/steady", "octocat/new"]
    assert cached.status_code == 304
    assert cached.content == b""


def test_snapshot_portfolio_trends_handle_empty_store_and_invalid_limit(
    tmp_path: Path,
) -> None:
    store = SnapshotStore(tmp_path / "snapshots.db")
    app.dependency_overrides[snapshot_store_dependency] = lambda: store
    try:
        response = client.get("/github/snapshots/trends")
        invalid = client.get("/github/snapshots/trends?limit=1")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "repositories_tracked": 0,
        "comparable_repositories": 0,
        "insufficient_data_repositories": 0,
        "fastest_growing_repository": None,
        "total_net_changes": {"stars": 0, "forks": 0, "open_issues": 0},
        "total_per_day": {"stars": 0, "forks": 0, "open_issues": 0},
        "repositories": [],
    }
    assert invalid.status_code == 422


def test_snapshot_portfolio_report_combines_state_delta_and_velocity(
    tmp_path: Path,
) -> None:
    store = SnapshotStore(tmp_path / "snapshots.db")
    store.save(snapshot(
        "2026-09-27T12:00:00+00:00",
        repository="octocat/growing",
        stars=10,
        forks=2,
        open_issues=8,
    ))
    store.save(snapshot(
        "2026-09-29T12:00:00+00:00",
        repository="octocat/growing",
        stars=16,
        forks=4,
        open_issues=6,
        language="=PYTHON()",
    ))
    store.save(snapshot(
        "2026-09-29T12:00:00+00:00",
        repository="octocat/new",
        stars=1,
    ))
    app.dependency_overrides[snapshot_store_dependency] = lambda: store
    try:
        response = client.get("/github/snapshots/report.csv?trend_limit=30")
    finally:
        app.dependency_overrides.clear()

    rows = list(csv.DictReader(StringIO(response.text)))
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"] == (
        'attachment; filename="devpulse-portfolio-report.csv"'
    )
    assert [row["repository"] for row in rows] == [
        "octocat/growing", "octocat/new",
    ]
    assert rows[0] == {
        "repository": "octocat/growing",
        "status": "ready",
        "collected_at": "2026-09-29T12:00:00+00:00",
        "language": "'=PYTHON()",
        "archived": "False",
        "stars": "16",
        "forks": "4",
        "open_issues": "6",
        "stars_change": "6",
        "forks_change": "2",
        "open_issues_change": "-2",
        "stars_per_day": "3.0",
        "forks_per_day": "1.0",
        "open_issues_per_day": "-1.0",
    }
    assert rows[1]["status"] == "insufficient_data"
    assert rows[1]["stars_change"] == ""
    assert rows[1]["stars_per_day"] == ""


def test_snapshot_portfolio_report_handles_empty_store_and_validates_limit(
    tmp_path: Path,
) -> None:
    store = SnapshotStore(tmp_path / "snapshots.db")
    app.dependency_overrides[snapshot_store_dependency] = lambda: store
    try:
        response = client.get("/github/snapshots/report.csv")
        invalid = client.get("/github/snapshots/report.csv?trend_limit=1")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert list(csv.DictReader(StringIO(response.text))) == []
    assert invalid.status_code == 422


def test_snapshot_portfolio_alerts_prioritize_actionable_changes(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "snapshots.db")
    store.save(snapshot(
        "2026-09-28T12:00:00+00:00",
        repository="octocat/risky",
        stars=10,
        open_issues=2,
    ))
    store.save(snapshot(
        "2026-09-29T12:00:00+00:00",
        repository="octocat/risky",
        stars=8,
        open_issues=15,
        archived=True,
        default_branch="develop",
    ))
    store.save(snapshot(
        "2026-09-28T12:00:00+00:00",
        repository="octocat/restored",
        archived=True,
    ))
    store.save(snapshot(
        "2026-09-29T12:00:00+00:00",
        repository="octocat/restored",
        archived=False,
    ))
    store.save(snapshot(
        "2026-09-29T12:00:00+00:00",
        repository="octocat/new",
    ))
    app.dependency_overrides[snapshot_store_dependency] = lambda: store
    try:
        response = client.get("/github/snapshots/alerts?issue_spike_threshold=5")
        cached = client.get(
            "/github/snapshots/alerts?issue_spike_threshold=5",
            headers={"If-None-Match": response.headers["etag"]},
        )
    finally:
        app.dependency_overrides.clear()

    payload = response.json()
    assert response.status_code == 200
    assert payload["repositories_tracked"] == 3
    assert payload["repositories_evaluated"] == 2
    assert payload["insufficient_data_repositories"] == ["octocat/new"]
    assert payload["alert_count"] == 5
    assert payload["severity_counts"] == {"critical": 2, "warning": 2, "info": 1}
    assert [alert["type"] for alert in payload["alerts"]] == [
        "open_issue_spike",
        "repository_archived",
        "default_branch_changed",
        "stars_lost",
        "repository_reactivated",
    ]
    assert cached.status_code == 304


def test_snapshot_portfolio_alerts_handle_no_data_and_validate_threshold(
    tmp_path: Path,
) -> None:
    store = SnapshotStore(tmp_path / "snapshots.db")
    app.dependency_overrides[snapshot_store_dependency] = lambda: store
    try:
        response = client.get("/github/snapshots/alerts")
        invalid = client.get("/github/snapshots/alerts?issue_spike_threshold=0")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "repositories_tracked": 0,
        "repositories_evaluated": 0,
        "insufficient_data_repositories": [],
        "issue_spike_threshold": 10,
        "alert_count": 0,
        "severity_counts": {"critical": 0, "warning": 0, "info": 0},
        "alerts": [],
    }
    assert invalid.status_code == 422
