import pytest

from app.review_throughput import analyze_review_throughput


def test_empty_history_returns_no_data():
    report = analyze_review_throughput([])
    assert report.status == "no_data"
    assert report.total_reviews == 0


def test_consistent_review_activity_is_steady():
    report = analyze_review_throughput([3, 2, 4, 0, 3])
    assert report.status == "steady"
    assert report.total_reviews == 12
    assert report.active_day_rate_percent == 80.0
    assert report.peak_reviews == 4


def test_sparse_review_activity_is_intermittent():
    report = analyze_review_throughput([0, 2, 0, 0, 1])
    assert report.status == "intermittent"
    assert report.median_reviews_per_day == 0.0


def test_zero_activity_is_idle():
    assert analyze_review_throughput([0, 0, 0]).status == "idle"


@pytest.mark.parametrize("counts", [[1, -1], [True, 2], [1.5, 2]])
def test_invalid_counts_are_rejected(counts):
    with pytest.raises(ValueError):
        analyze_review_throughput(counts)


def test_invalid_active_rate_threshold_is_rejected():
    with pytest.raises(ValueError):
        analyze_review_throughput([1], minimum_active_rate_percent=101)
