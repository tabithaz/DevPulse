from app.gaps import analyze_activity_gaps


def test_gap_analysis_tracks_recovery_and_longest_gap():
    result = analyze_activity_gaps([3, 0, 0, 4, 1, 0, 2])
    assert result == {
        "days_observed": 7,
        "inactive_days": 3,
        "inactivity_rate": 42.9,
        "gap_count": 2,
        "longest_gap_days": 2,
        "current_gap_days": 0,
        "average_gap_days": 1.5,
        "median_gap_days": 1.5,
        "recovery_events": 6,
        "status": "inconsistent",
    }


def test_long_gap_is_at_risk():
    assert analyze_activity_gaps([1, 0, 0, 0, 0, 0, 2])["status"] == "at_risk"


def test_empty_history_is_consistent():
    result = analyze_activity_gaps([])
    assert result["status"] == "consistent"
    assert result["average_gap_days"] == 0.0
    assert result["median_gap_days"] == 0.0
    assert result["current_gap_days"] == 0


def test_average_gap_days_summarizes_inactivity_bursts():
    result = analyze_activity_gaps([0, 0, 3, 0, 4, 0, 0, 0])
    assert result["gap_count"] == 3
    assert result["inactive_days"] == 6
    assert result["average_gap_days"] == 2.0


def test_median_gap_days_limits_outlier_influence():
    result = analyze_activity_gaps([0, 1, 0, 1, 0, 0, 0, 0, 0])
    assert result["average_gap_days"] == 2.3
    assert result["median_gap_days"] == 1.0


def test_current_gap_days_tracks_ongoing_inactivity():
    assert analyze_activity_gaps([4, 0, 2, 0, 0])["current_gap_days"] == 2
    assert analyze_activity_gaps([4, 0, 2])["current_gap_days"] == 0


def test_invalid_activity_rejected():
    for invalid in ([1, -1], [1, True], [False, 2]):
        try:
            analyze_activity_gaps(invalid)
            assert False
        except ValueError:
            pass
