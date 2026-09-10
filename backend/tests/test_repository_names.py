from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_repository_names_are_trimmed_before_summary() -> None:
    response = client.post(
        "/activity/summary",
        json={"repositories": [{"name": "  api-service  ", "commits": 2}]},
    )

    assert response.status_code == 200
    assert response.json()["most_active_repository"] == "api-service"


def test_duplicate_repository_names_reject_surrounding_whitespace() -> None:
    response = client.post(
        "/activity/summary",
        json={
            "repositories": [
                {"name": "api-service", "commits": 1},
                {"name": "  API-SERVICE  ", "commits": 2},
            ]
        },
    )

    assert response.status_code == 422
    assert "repository names must be unique" in response.text


def test_blank_repository_name_is_rejected() -> None:
    response = client.post(
        "/activity/summary",
        json={"repositories": [{"name": "   ", "commits": 1}]},
    )

    assert response.status_code == 422
    assert "repository name must not be blank" in response.text
