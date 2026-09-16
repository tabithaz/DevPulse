import pytest

from app.merge_queue import analyze_merge_queue


def test_empty_queue():
    report = analyze_merge_queue([])
    assert report.status == "empty"
    assert report.queued_changes == 0


def test_healthy_queue():
    report = analyze_merge_queue([4, 8, 12])
    assert report.status == "healthy"
    assert report.median_wait_minutes == 8.0


def test_queue_needs_attention():
    report = analyze_merge_queue([5, 10, 35, 40])
    assert report.status == "congested"
    assert report.stale_changes == 2


def test_old_change_marks_queue_congested():
    report = analyze_merge_queue([5, 12, 95])
    assert report.status == "congested"
    assert report.oldest_wait_minutes == 95.0


def test_invalid_thresholds_are_rejected():
    with pytest.raises(ValueError):
        analyze_merge_queue([10], warning_minutes=90, critical_minutes=30)
