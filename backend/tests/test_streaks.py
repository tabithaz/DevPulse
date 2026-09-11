import pytest

from app.streaks import analyze_contribution_streak


def test_analyze_contribution_streak_tracks_current_and_longest_runs() -> None:
    result = analyze_contribution_streak([1, 2, 0, 3, 4, 5])

    assert result == {
        "days_observed": 6,
        "active_days": 5,
        "current_streak": 3,
        "longest_streak": 3,
        "consistency_percent": 83.3,
    }


def test_analyze_contribution_streak_handles_inactive_tail() -> None:
    result = analyze_contribution_streak([2, 1, 1, 0, 0])

    assert result["current_streak"] == 0
    assert result["longest_streak"] == 3
    assert result["consistency_percent"] == 60.0


def test_analyze_contribution_streak_handles_empty_history() -> None:
    assert analyze_contribution_streak([]) == {
        "days_observed": 0,
        "active_days": 0,
        "current_streak": 0,
        "longest_streak": 0,
        "consistency_percent": 0.0,
    }


def test_analyze_contribution_streak_rejects_negative_counts() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        analyze_contribution_streak([1, -1, 2])
