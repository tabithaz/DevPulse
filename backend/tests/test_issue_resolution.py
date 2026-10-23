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

@pytest.mark.parametrize("invalid_hours", [float("nan"), float("inf"), -float("inf"), True, "12"])
def test_rejects_invalid_resolution_measurements(invalid_hours):
    with pytest.raises(ValueError, match="resolution hours"):
        analyze_issue_resolution([12, invalid_hours])


@pytest.mark.parametrize("invalid_sla", [float("nan"), float("inf"), -float("inf"), True, "72"])
def test_rejects_invalid_sla_thresholds(invalid_sla):
    with pytest.raises(ValueError, match="sla_hours"):
        analyze_issue_resolution([12], sla_hours=invalid_sla)


def test_zero_resolution_hours_is_valid():
    report = analyze_issue_resolution([0, 0, 24])
    assert report.resolved_issues == 3
    assert report.median_resolution_hours == 0.0
