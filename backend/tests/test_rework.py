import pytest

from app.rework import analyze_rework


def test_reports_healthy_single_round_reviews():
    report = analyze_rework([1, 1, 1, 1])

    assert report.average_review_rounds == 1.0
    assert report.rework_rate_percent == 0.0
    assert report.status == "healthy"


def test_reports_watch_level_rework():
    report = analyze_rework([1, 1, 1, 2])

    assert report.reworked_pull_requests == 1
    assert report.rework_rate_percent == 25.0
    assert report.status == "watch"


def test_reports_high_rework():
    report = analyze_rework([1, 2, 3, 2])

    assert report.total_review_rounds == 8
    assert report.average_review_rounds == 2.0
    assert report.status == "high_rework"


def test_empty_history_returns_no_data():
    assert analyze_rework([]).status == "no_data"


def test_rejects_invalid_round_counts():
    with pytest.raises(ValueError):
        analyze_rework([1, 0, 2])
