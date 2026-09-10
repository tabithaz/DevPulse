from fastapi.testclient import TestClient

from app.main import activity_diversity, app

client = TestClient(app)


def test_activity_diversity_balanced_mix_scores_high() -> None:
    score, label = activity_diversity([10, 10, 10])
    assert score == 100.0
    assert label == "diverse"


def test_activity_diversity_single_activity_type_is_specialized() -> None:
    score, label = activity_diversity([12, 0, 0])
    assert score == 0.0
    assert label == "specialized"


def test_activity_summary_exposes_diversity_metrics() -> None:
    response = client.post(
        "/activity/summary",
        json={
            "repositories": [
                {"name": "api", "commits": 6, "pull_requests": 3, "issues": 3},
                {"name": "web", "commits": 3, "pull_requests": 3, "issues": 3},
            ]
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["activity_diversity_score"] == 98.0
    assert body["activity_diversity"] == "diverse"


def test_activity_diversity_empty_activity_has_no_label() -> None:
    score, label = activity_diversity([0, 0, 0])
    assert score == 0.0
    assert label is None
