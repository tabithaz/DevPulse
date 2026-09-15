import pytest

from app.issue_resolution import analyze_issue_resolution


def test_healthy_resolution_window():
    report = analyze_issue_resolution([12, 24, 36])
    assert report.resolved_issues == 3
    assert report.median_resolution_hours == 24.0
    assert report.status == "healthy"


def test_watch_when_some_issues_breach_sla():
    report = analyze_issue_resolution([12] * 9 + [100])
    assert report.sla_breach_rate_percent == 10.0
    assert report.status == "watch"


def test_slow_when_breach_rate_is_high():
    report = analyze_issue_resolution([12, 100, 120])
    assert report.status == "slow"
    assert report.p90_resolution_hours == 120.0


def test_empty_history_returns_no_data():
    assert analyze_issue_resolution([]).status == "no_data"


def test_rejects_invalid_values():
    with pytest.raises(ValueError):
        analyze_issue_resolution([-1])
    with pytest.raises(ValueError):
        analyze_issue_resolution([1], sla_hours=0)
