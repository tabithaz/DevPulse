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


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -float("inf"), True, False, "24", None, 10**400])
def test_rejects_nonfinite_or_nonnumeric_review_times(invalid):
    with pytest.raises(ValueError):
        analyze_review_latency([1, invalid])


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -float("inf"), True, False, "24", None, 10**400])
def test_rejects_invalid_target_hours(invalid):
    with pytest.raises(ValueError):
        analyze_review_latency([1], target_hours=invalid)


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -float("inf"), True, False, "40", None, 10**400])
def test_rejects_invalid_critical_overdue_percent(invalid):
    with pytest.raises(ValueError):
        analyze_review_latency([1], critical_overdue_percent=invalid)


def test_large_finite_review_times_do_not_overflow_median():
    report = analyze_review_latency([1e308, 1e308])
    assert report.median_first_review_hours == 1e308
    assert report.p90_first_review_hours == 1e308
    assert report.status == "critical"


def test_large_finite_mixed_review_times_have_finite_midpoint():
    report = analyze_review_latency([0, 1e308])
    assert report.median_first_review_hours == 5e307
    assert report.overdue_reviews == 1


def test_zero_latency_and_exact_target_are_not_overdue():
    report = analyze_review_latency([0, 24], target_hours=24)
    assert report.median_first_review_hours == 12.0
    assert report.overdue_reviews == 0
    assert report.status == "healthy"


def test_invalid_threshold_rejected_even_for_empty_history():
    with pytest.raises(ValueError):
        analyze_review_latency([], target_hours=float("nan"))
