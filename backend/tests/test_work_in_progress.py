import pytest

from app.work_in_progress import analyze_work_in_progress


def test_empty_work_in_progress_has_no_data_status():
    report = analyze_work_in_progress([])
    assert report.status == "no_data"
    assert report.open_changes == 0


def test_fresh_changes_are_healthy():
    report = analyze_work_in_progress([2, 8, 12, 24])
    assert report.status == "healthy"
    assert report.aging_changes == 0
    assert report.median_age_hours == 10.0


def test_some_aging_changes_trigger_watch_status():
    report = analyze_work_in_progress([4, 8, 60, 12, 20])
    assert report.status == "watch"
    assert report.aging_rate_percent == 20.0


def test_high_aging_rate_is_congested():
    report = analyze_work_in_progress([4, 60, 72, 12, 96])
    assert report.status == "congested"
    assert report.aging_changes == 3


@pytest.mark.parametrize("ages", [[-1], [True], ["12"]])
def test_invalid_change_ages_are_rejected(ages):
    with pytest.raises(ValueError):
        analyze_work_in_progress(ages)


def test_invalid_thresholds_are_rejected():
    with pytest.raises(ValueError):
        analyze_work_in_progress([1], aging_hours=0)
    with pytest.raises(ValueError):
        analyze_work_in_progress([1], critical_rate_percent=101)
