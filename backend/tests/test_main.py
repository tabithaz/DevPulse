from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_check() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_activity_summary_aggregates_repository_metrics() -> None:
    response = client.post(
        "/activity/summary",
        json={
            "repositories": [
                {
                    "name": "api-service",
                    "commits": 8,
                    "pull_requests": 2,
                    "issues": 1,
                },
                {
                    "name": "dashboard-ui",
                    "commits": 0,
                    "pull_requests": 0,
                    "issues": 0,
                },
            ]
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "repositories_tracked": 2,
        "active_repositories": 1,
        "activity_coverage_percent": 50.0,
        "total_commits": 8,
        "total_pull_requests": 2,
        "total_issues": 1,
        "total_events": 11,
        "most_active_repository": "api-service",
        "most_active_repository_events": 11,
    }


def test_activity_summary_uses_deterministic_tie_breaking() -> None:
    response = client.post(
        "/activity/summary",
        json={
            "repositories": [
                {
                    "name": "api-service",
                    "commits": 3,
                    "pull_requests": 1,
                    "issues": 0,
                },
                {
                    "name": "dashboard-ui",
                    "commits": 2,
                    "pull_requests": 2,
                    "issues": 0,
                },
            ]
        },
    )

    assert response.status_code == 200
    assert response.json()["most_active_repository"] == "dashboard-ui"
    assert response.json()["most_active_repository_events"] == 4
    assert response.json()["total_events"] == 8
    assert response.json()["activity_coverage_percent"] == 100.0


def test_activity_summary_handles_empty_repository_list() -> None:
    response = client.post("/activity/summary", json={"repositories": []})

    assert response.status_code == 200
    assert response.json()["most_active_repository"] is None
    assert response.json()["most_active_repository_events"] == 0
    assert response.json()["total_events"] == 0
    assert response.json()["activity_coverage_percent"] == 0.0


def test_activity_summary_rejects_negative_counts() -> None:
    response = client.post(
        "/activity/summary",
        json={
            "repositories": [
                {
                    "name": "api-service",
                    "commits": -1,
                    "pull_requests": 0,
                    "issues": 0,
                }
            ]
        },
    )

    assert response.status_code == 422
