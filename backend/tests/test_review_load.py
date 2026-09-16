import pytest

from app.review_load import analyze_review_load


def test_balanced_review_load():
    report = analyze_review_load({"alex": 10, "sam": 9, "lee": 11})
    assert report.status == "balanced"
    assert report.total_reviews == 30
    assert report.reviewer_count == 3


def test_concentrated_review_load():
    report = analyze_review_load({"alex": 18, "sam": 2, "lee": 0})
    assert report.status == "concentrated"
    assert report.busiest_reviewer_share_percent == 90.0


def test_ignores_inactive_reviewers_in_distribution():
    report = analyze_review_load({"alex": 4, "sam": 4, "lee": 0})
    assert report.reviewer_count == 2
    assert report.load_imbalance_ratio == 1.0


def test_no_review_data():
    assert analyze_review_load({"alex": 0}).status == "no_data"


def test_rejects_invalid_counts():
    with pytest.raises(ValueError):
        analyze_review_load({"alex": -1})
