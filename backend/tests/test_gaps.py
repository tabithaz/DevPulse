from app.gaps import analyze_activity_gaps


def test_gap_analysis_tracks_recovery_and_longest_gap():
    result = analyze_activity_gaps([3, 0, 0, 4, 1, 0, 2])
    assert result == {
        "days_observed": 7,
        "inactive_days": 3,
        "inactivity_rate": 42.9,
        "gap_count": 2,
        "longest_gap_days": 2,
        "recovery_events": 6,
        "status": "inconsistent",
    }


def test_long_gap_is_at_risk():
    assert analyze_activity_gaps([1, 0, 0, 0, 0, 0, 2])["status"] == "at_risk"


def test_empty_history_is_consistent():
    assert analyze_activity_gaps([])["status"] == "consistent"


def test_invalid_activity_rejected():
    try:
        analyze_activity_gaps([1, -1])
        assert False
    except ValueError:
        pass
