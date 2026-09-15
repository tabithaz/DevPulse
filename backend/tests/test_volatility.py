import pytest

from app.volatility import analyze_activity_volatility


def test_stable_activity():
    result = analyze_activity_volatility([5, 6, 5, 6, 5])
    assert result["status"] == "stable"
    assert result["peak_to_average_ratio"] < 1.2
    assert result["longest_inactive_streak_days"] == 0


def test_volatile_activity():
    result = analyze_activity_volatility([0, 0, 1, 0, 20])
    assert result["status"] == "volatile"
    assert result["coefficient_of_variation"] > 1
    assert result["longest_inactive_streak_days"] == 2


def test_inactive_activity():
    result = analyze_activity_volatility([0, 0, 0])
    assert result["status"] == "inactive"
    assert result["longest_inactive_streak_days"] == 3


def test_inactive_streak_resets_after_activity():
    result = analyze_activity_volatility([0, 0, 4, 0, 0, 0, 2, 0])
    assert result["longest_inactive_streak_days"] == 3


def test_invalid_activity_rejected():
    with pytest.raises(ValueError):
        analyze_activity_volatility([1, -1, 2])
