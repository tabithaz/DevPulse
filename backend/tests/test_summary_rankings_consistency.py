from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_summary_leader_matches_rankings_when_activity_is_tied() -> None:
    payload = {
        "repositories": [
            {"name": "zeta", "commits": 2},
            {"name": "Alpha", "commits": 2},
        ]
    }

    summary_response = client.post("/activity/summary", json=payload)
    rankings_response = client.post("/activity/rankings", json=payload)

    assert summary_response.status_code == 200
    assert rankings_response.status_code == 200
    assert summary_response.json()["most_active_repository"] == "Alpha"
    assert rankings_response.json()[0]["repository"] == "Alpha"
