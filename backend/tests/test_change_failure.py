from app.change_failure import analyze_change_failure


def test_healthy_failure_rate():
    report = analyze_change_failure([True] * 9 + [False])
    assert report.failure_rate_percent == 10.0
    assert report.status == "healthy"


def test_watch_failure_rate():
    assert analyze_change_failure([True] * 4 + [False]).status == "watch"


def test_critical_failure_rate():
    assert analyze_change_failure([True, False, False]).status == "critical"


def test_empty_history_returns_no_data():
    assert analyze_change_failure([]).status == "no_data"


def test_threshold_validation():
    import pytest

    with pytest.raises(ValueError):
        analyze_change_failure([True], warning_percent=30, critical_percent=20)
