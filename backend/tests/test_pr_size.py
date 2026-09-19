import pytest

from app.pr_size import analyze_pull_request_sizes


def test_reports_healthy_small_pull_requests():
    report = analyze_pull_request_sizes([40, 80, 120])
    assert report.median_changed_lines == 80.0
    assert report.largest_changed_lines == 120
    assert report.oversized_pull_requests == 0
    assert report.status == "healthy"


def test_reports_watch_for_isolated_large_pull_request():
    report = analyze_pull_request_sizes([50, 100, 450])
    assert report.oversized_rate_percent == 33.3
    assert report.status == "watch"


def test_reports_high_risk_for_critical_pull_request():
    assert analyze_pull_request_sizes([50, 1200]).status == "high_risk"


def test_reports_high_risk_when_large_changes_are_common():
    assert analyze_pull_request_sizes([100, 450, 500, 600]).status == "high_risk"


def test_handles_empty_input():
    assert analyze_pull_request_sizes([]).status == "no_data"


@pytest.mark.parametrize("values", [[-1], [True], [1.5]])
def test_rejects_invalid_changed_line_counts(values):
    with pytest.raises(ValueError):
        analyze_pull_request_sizes(values)
