from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_activity_rankings_orders_by_events_and_reports_share() -> None:
    response = client.post(
        "/activity/rankings?limit=2",
        json={
            "repositories": [
                {"name": "api", "commits": 5, "pull_requests": 1, "issues": 0},
                {"name": "web", "commits": 2, "pull_requests": 1, "issues": 1},
                {"name": "worker", "commits": 1, "pull_requests": 0, "issues": 0},
            ]
        },
    )

    assert response.status_code == 200
    assert response.json() == [
        {"rank": 1, "repository": "api", "events": 6, "share_percent": 54.5},
        {"rank": 2, "repository": "web", "events": 4, "share_percent": 36.4},
    ]


def test_activity_rankings_breaks_ties_by_name() -> None:
    response = client.post(
        "/activity/rankings",
        json={"repositories": [{"name": "zeta", "commits": 2}, {"name": "alpha", "commits": 2}]},
    )

    assert response.status_code == 200
    assert [item["repository"] for item in response.json()] == ["alpha", "zeta"]


def test_activity_rankings_validates_limit() -> None:
    response = client.post("/activity/rankings?limit=0", json={"repositories": []})
    assert response.status_code == 422
