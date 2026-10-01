from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

import app.main as main
from app.github_client import RepositorySnapshot
from app.snapshot_store import SnapshotStore, snapshot_store_dependency


client = TestClient(main.app)
NOW = datetime(2026, 10, 1, 16, 0, tzinfo=timezone.utc)


def snapshot(repository: str, collected_at: str) -> RepositorySnapshot:
    return RepositorySnapshot(
        repository=repository,
        description=None,
        default_branch="main",
        language="Python",
        stars=1,
        forks=0,
        open_issues=0,
        archived=False,
        created_at="2026-01-01T00:00:00Z",
        pushed_at="2026-10-01T00:00:00Z",
        collected_at=collected_at,
    )


@pytest.fixture
def freshness_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = SnapshotStore(tmp_path / "snapshots.db")
    store.save(snapshot("tabithaz/fresh", "2026-10-01T10:00:00+00:00"))
    store.save(snapshot("tabithaz/stale", "2026-09-29T16:00:00+00:00"))
    app = main.app
    app.dependency_overrides[snapshot_store_dependency] = lambda: store
    monkeypatch.setattr(main, "utc_now", lambda: NOW)
    try:
        yield store
    finally:
        app.dependency_overrides.clear()


def test_freshness_endpoint_prioritizes_stale_repositories(freshness_store) -> None:
    response = client.get("/github/snapshots/freshness?max_age_hours=24")

    assert response.status_code == 200
    assert response.json() == {
        "status": "stale",
        "evaluated_at": "2026-10-01T16:00:00+00:00",
        "max_age_hours": 24.0,
        "repositories_tracked": 2,
        "fresh_repositories": 1,
        "stale_repositories": 1,
        "freshest_snapshot_age_hours": 6.0,
        "stalest_snapshot_age_hours": 48.0,
        "next_stale_at": "2026-10-02T10:00:00+00:00",
        "repositories": [
            {
                "repository": "tabithaz/stale",
                "status": "stale",
                "collected_at": "2026-09-29T16:00:00+00:00",
                "age_hours": 48.0,
                "stale_by_hours": 24.0,
                "becomes_stale_at": "2026-09-30T16:00:00+00:00",
            },
            {
                "repository": "tabithaz/fresh",
                "status": "fresh",
                "collected_at": "2026-10-01T10:00:00+00:00",
                "age_hours": 6.0,
                "stale_by_hours": 0.0,
                "becomes_stale_at": "2026-10-02T10:00:00+00:00",
            },
        ],
    }


def test_freshness_uses_only_latest_snapshot(freshness_store) -> None:
    freshness_store.save(snapshot(
        "tabithaz/stale",
        "2026-10-01T15:00:00+00:00",
    ))

    response = client.get("/github/snapshots/freshness?max_age_hours=24")

    assert response.json()["status"] == "fresh"
    assert response.json()["stale_repositories"] == 0
    assert response.json()["repositories_tracked"] == 2
    assert response.json()["freshest_snapshot_age_hours"] == 1.0


def test_freshness_handles_empty_portfolio(tmp_path: Path, monkeypatch) -> None:
    store = SnapshotStore(tmp_path / "snapshots.db")
    main.app.dependency_overrides[snapshot_store_dependency] = lambda: store
    monkeypatch.setattr(main, "utc_now", lambda: NOW)
    try:
        response = client.get("/github/snapshots/freshness")
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["status"] == "no_data"
    assert response.json()["repositories"] == []
    assert response.json()["next_stale_at"] is None


@pytest.mark.parametrize("max_age_hours", [0, -1, 8761, "not-a-number"])
def test_freshness_validates_sla(max_age_hours) -> None:
    response = client.get(
        "/github/snapshots/freshness",
        params={"max_age_hours": max_age_hours},
    )

    assert response.status_code == 422
