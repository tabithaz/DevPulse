import pytest

from app.release_stability import analyze_release_stability


def test_clean_releases_are_stable():
    report = analyze_release_stability([(False, False)] * 8)
    assert report.clean_release_rate_percent == 100.0
    assert report.status == "stable"


def test_interventions_are_counted_once_per_release():
    report = analyze_release_stability(
        [(False, False)] * 8 + [(True, True), (False, False)]
    )
    assert report.rollback_count == 1
    assert report.hotfix_count == 1
    assert report.intervention_rate_percent == 10.0


def test_watch_and_unstable_thresholds():
    watch = analyze_release_stability([(False, False)] * 4 + [(False, True)])
    unstable = analyze_release_stability([(False, False), (True, False)])
    assert watch.status == "watch"
    assert unstable.status == "unstable"


def test_empty_history_returns_no_data():
    assert analyze_release_stability([]).status == "no_data"


def test_invalid_thresholds_are_rejected():
    with pytest.raises(ValueError):
        analyze_release_stability([(False, False)], 30, 20)
