import pytest

from app.branch_staleness import analyze_branch_staleness


def test_healthy_when_all_branches_are_recent():
    report = analyze_branch_staleness([1, 3, 7, 10])
    assert report.status == "healthy"
    assert report.stale_branches == 0


def test_watch_when_some_branches_are_stale():
    report = analyze_branch_staleness([2, 5, 15, 20], critical_rate_percent=75)
    assert report.status == "watch"
    assert report.stale_branches == 2
    assert report.stale_rate_percent == 50.0


def test_critical_when_stale_rate_reaches_threshold():
    report = analyze_branch_staleness([2, 15, 20, 30])
    assert report.status == "critical"
    assert report.median_age_days == 17.5


def test_empty_input_returns_no_data():
    assert analyze_branch_staleness([]).status == "no_data"


def test_invalid_configuration_is_rejected():
    with pytest.raises(ValueError):
        analyze_branch_staleness([1], stale_after_days=0)
    with pytest.raises(ValueError):
        analyze_branch_staleness([-1])
