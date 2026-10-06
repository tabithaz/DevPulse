from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

import app.main as main
from app.github_client import RepositorySnapshot
from app.snapshot_store import SnapshotStore, snapshot_store_dependency


client = TestClient(main.app)
NOW = datetime(2026, 10, 6, 16, 0, tzinfo=timezone.utc)


def snapshot(repository: str, collected_at: str, **values) -> RepositorySnapshot:
    return RepositorySnapshot(
        repository=repository,
        description=None,
        default_branch="main",
        language="Python",
        stars=values.get("stars", 1),
        forks=values.get("forks", 0),
        open_issues=values.get("open_issues", 0),
        archived=values.get("archived", False),
        created_at="2026-01-01T00:00:00Z",
        pushed_at="2026-10-06T00:00:00Z",
        collected_at=collected_at,
    )


@pytest.fixture
def metrics_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = SnapshotStore(tmp_path / "snapshots.db")
    store.save(snapshot(
        'tabithaz/api\\"service',
        "2026-10-06T14:00:00+00:00",
        stars=12,
        forks=3,
        open_issues=4,
    ))
    store.save(snapshot(
        "tabithaz/legacy",
        "2026-10-04T16:00:00+00:00",
        stars=5,
        forks=1,
        open_issues=2,
        archived=True,
    ))
    main.app.dependency_overrides[snapshot_store_dependency] = lambda: store
    monkeypatch.setattr(main, "utc_now", lambda: NOW)
    try:
        yield store
    finally:
        main.app.dependency_overrides.clear()


def test_metrics_exposes_portfolio_and_freshness_gauges(metrics_store) -> None:
    response = client.get("/metrics?max_age_hours=24")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain; version=0.0.4")
    assert "devpulse_repositories_tracked 2" in response.text
    assert "devpulse_repositories_archived 1" in response.text
    assert "devpulse_stars_total 17" in response.text
    assert "devpulse_forks_total 4" in response.text
    assert "devpulse_open_issues_total 6" in response.text
    assert "devpulse_snapshots_stale 1" in response.text
    assert 'devpulse_snapshot_age_seconds{repository="tabithaz/api\\\\\\"service"} 7200' in response.text
    assert 'devpulse_snapshot_stale{repository="tabithaz/legacy"} 1' in response.text


def test_metrics_uses_only_latest_snapshot(metrics_store) -> None:
    metrics_store.save(snapshot(
        "tabithaz/legacy",
        "2026-10-06T15:00:00+00:00",
        stars=8,
        forks=2,
        open_issues=1,
    ))

    response = client.get("/metrics?max_age_hours=24")

    assert "devpulse_stars_total 20" in response.text
    assert "devpulse_snapshots_stale 0" in response.text
    assert 'devpulse_snapshot_age_seconds{repository="tabithaz/legacy"} 3600' in response.text


def test_metrics_handles_empty_portfolio(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "empty.db")
    main.app.dependency_overrides[snapshot_store_dependency] = lambda: store
    try:
        response = client.get("/metrics")
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 200
    assert "devpulse_repositories_tracked 0" in response.text
    assert "devpulse_snapshots_stale 0" in response.text
    assert "devpulse_snapshot_age_seconds{" not in response.text


@pytest.mark.parametrize("max_age_hours", [0, -1, 8761, "invalid"])
def test_metrics_validates_freshness_sla(max_age_hours) -> None:
    response = client.get("/metrics", params={"max_age_hours": max_age_hours})

    assert response.status_code == 422
