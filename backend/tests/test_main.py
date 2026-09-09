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
        "inactive_repositories": 1,
        "activity_coverage_percent": 50.0,
        "average_events_per_active_repository": 11.0,
        "total_commits": 8,
        "total_pull_requests": 2,
        "total_issues": 1,
        "total_events": 11,
        "commit_share_percent": 72.7,
        "pull_request_share_percent": 18.2,
        "issue_share_percent": 9.1,
        "dominant_activity_type": "commits",
        "dominant_activity_events": 8,
        "most_active_repository": "api-service",
        "most_active_repository_events": 11,
        "most_active_repository_share_percent": 100.0,
        "activity_concentration": "highly_concentrated",
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
    assert response.json()["most_active_repository_share_percent"] == 50.0
    assert response.json()["activity_concentration"] == "concentrated"
    assert response.json()["dominant_activity_type"] == "commits"
    assert response.json()["dominant_activity_events"] == 5
    assert response.json()["total_events"] == 8
    assert response.json()["activity_coverage_percent"] == 100.0
    assert response.json()["inactive_repositories"] == 0
    assert response.json()["commit_share_percent"] == 62.5
    assert response.json()["pull_request_share_percent"] == 37.5
    assert response.json()["issue_share_percent"] == 0.0


def test_activity_summary_marks_distributed_activity_as_balanced() -> None:
    response = client.post(
        "/activity/summary",
        json={
            "repositories": [
                {"name": "api", "commits": 4, "pull_requests": 0, "issues": 0},
                {"name": "web", "commits": 3, "pull_requests": 0, "issues": 0},
                {"name": "worker", "commits": 3, "pull_requests": 0, "issues": 0},
            ]
        },
    )

    assert response.status_code == 200
    assert response.json()["most_active_repository_share_percent"] == 40.0
    assert response.json()["activity_concentration"] == "balanced"


def test_activity_summary_handles_empty_repository_list() -> None:
    response = client.post("/activity/summary", json={"repositories": []})

    assert response.status_code == 200
    assert response.json()["most_active_repository"] is None
    assert response.json()["most_active_repository_events"] == 0
    assert response.json()["most_active_repository_share_percent"] == 0.0
    assert response.json()["activity_concentration"] is None
    assert response.json()["dominant_activity_type"] is None
    assert response.json()["dominant_activity_events"] == 0
    assert response.json()["total_events"] == 0
    assert response.json()["activity_coverage_percent"] == 0.0
    assert response.json()["inactive_repositories"] == 0
    assert response.json()["commit_share_percent"] == 0.0
    assert response.json()["pull_request_share_percent"] == 0.0
    assert response.json()["issue_share_percent"] == 0.0


def test_activity_summary_breaks_activity_type_ties_deterministically() -> None:
    response = client.post(
        "/activity/summary",
        json={
            "repositories": [
                {
                    "name": "api-service",
                    "commits": 2,
                    "pull_requests": 2,
                    "issues": 2,
                }
            ]
        },
    )

    assert response.status_code == 200
    assert response.json()["dominant_activity_type"] == "pull_requests"
    assert response.json()["dominant_activity_events"] == 2


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
