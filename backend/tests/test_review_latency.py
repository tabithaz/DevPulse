import pytest

from app.review_latency import analyze_review_latency


def test_healthy_when_all_reviews_meet_target():
    report = analyze_review_latency([2, 6, 12, 18])
    assert report.status == "healthy"
    assert report.overdue_reviews == 0
    assert report.median_first_review_hours == 9.0


def test_watch_when_some_reviews_are_overdue():
    report = analyze_review_latency([2, 8, 12, 30, 36], critical_overdue_percent=50)
    assert report.status == "watch"
    assert report.overdue_reviews == 2
    assert report.overdue_rate_percent == 40.0


def test_critical_when_overdue_share_reaches_threshold():
    report = analyze_review_latency([2, 30, 36, 48])
    assert report.status == "critical"
    assert report.p90_first_review_hours == 48.0


def test_empty_history_returns_no_data():
    assert analyze_review_latency([]).status == "no_data"


def test_rejects_invalid_values():
    with pytest.raises(ValueError):
        analyze_review_latency([-1])
    with pytest.raises(ValueError):
        analyze_review_latency([1], target_hours=0)
