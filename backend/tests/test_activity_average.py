from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_average_events_per_active_repository() -> None:
    response = client.post(
        "/activity/summary",
        json={
            "repositories": [
                {"name": "api-service", "commits": 5},
                {"name": "dashboard-ui", "pull_requests": 2, "issues": 1},
                {"name": "docs", "commits": 0},
            ]
        },
    )

    assert response.status_code == 200
    assert response.json()["average_events_per_active_repository"] == 4.0


def test_average_events_is_zero_without_activity() -> None:
    response = client.post(
        "/activity/summary",
        json={"repositories": [{"name": "dashboard-ui"}]},
    )

    assert response.status_code == 200
    assert response.json()["average_events_per_active_repository"] == 0.0
