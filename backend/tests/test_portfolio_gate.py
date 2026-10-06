from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

import app.main as main
from app.github_client import RepositorySnapshot
from app.snapshot_store import SnapshotStore, snapshot_store_dependency


client = TestClient(main.app)
NOW = datetime(2026, 10, 6, 19, 0, tzinfo=timezone.utc)


def snapshot(repository: str, collected_at: str, **values) -> RepositorySnapshot:
    return RepositorySnapshot(
        repository=repository,
        description=None,
        default_branch=values.get("default_branch", "main"),
        language="Python",
        stars=values.get("stars", 10),
        forks=1,
        open_issues=values.get("open_issues", 2),
        archived=values.get("archived", False),
        created_at="2026-01-01T00:00:00Z",
        pushed_at="2026-10-06T00:00:00Z",
        collected_at=collected_at,
    )


@pytest.fixture
def gate_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = SnapshotStore(tmp_path / "snapshots.db")
    store.save(snapshot("tabithaz/stable", "2026-10-06T17:00:00+00:00"))
    store.save(snapshot("tabithaz/stable", "2026-10-06T18:00:00+00:00"))
    store.save(snapshot("tabithaz/risky", "2026-10-04T18:00:00+00:00"))
    store.save(snapshot(
        "tabithaz/risky",
        "2026-10-04T19:00:00+00:00",
        archived=True,
        open_issues=30,
    ))
    main.app.dependency_overrides[snapshot_store_dependency] = lambda: store
    monkeypatch.setattr(main, "utc_now", lambda: NOW)
    try:
        yield store
    finally:
        main.app.dependency_overrides.clear()


def test_portfolio_gate_fails_closed_with_actionable_checks(gate_store) -> None:
    response = client.get(
        "/github/snapshots/gate?max_age_hours=24&issue_spike_threshold=10"
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "fail",
        "evaluated_at": "2026-10-06T19:00:00+00:00",
        "checks": {
            "data_available": True,
            "freshness_budget_met": False,
            "critical_alert_budget_met": False,
            "warning_alert_budget_met": True,
        },
        "policy": {
            "max_age_hours": 24.0,
            "max_stale_repositories": 0,
            "max_critical_alerts": 0,
            "max_warning_alerts": 0,
            "issue_spike_threshold": 10,
        },
        "observed": {
            "repositories_tracked": 2,
            "stale_repositories": 1,
            "critical_alerts": 2,
            "warning_alerts": 0,
            "insufficient_data_repositories": 0,
        },
        "failing_checks": [
            "freshness_budget_met",
            "critical_alert_budget_met",
        ],
    }


def test_portfolio_gate_passes_with_explicit_budgets(gate_store) -> None:
    response = client.get(
        "/github/snapshots/gate",
        params={
            "max_age_hours": 24,
            "max_stale_repositories": 1,
            "max_critical_alerts": 2,
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "pass"
    assert response.json()["failing_checks"] == []


def test_portfolio_gate_fails_when_no_snapshot_data_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SnapshotStore(tmp_path / "empty.db")
    main.app.dependency_overrides[snapshot_store_dependency] = lambda: store
    monkeypatch.setattr(main, "utc_now", lambda: NOW)
    try:
        response = client.get("/github/snapshots/gate")
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["status"] == "fail"
    assert response.json()["failing_checks"] == ["data_available"]


@pytest.mark.parametrize(
    "parameter,value",
    [
        ("max_age_hours", 0),
        ("max_age_hours", 8761),
        ("max_stale_repositories", -1),
        ("max_critical_alerts", -1),
        ("max_warning_alerts", -1),
        ("issue_spike_threshold", 0),
    ],
)
def test_portfolio_gate_validates_policy(parameter, value) -> None:
    response = client.get("/github/snapshots/gate", params={parameter: value})

    assert response.status_code == 422
