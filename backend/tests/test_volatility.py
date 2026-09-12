import pytest

from app.volatility import analyze_activity_volatility


def test_stable_activity():
    result = analyze_activity_volatility([5, 6, 5, 6, 5])
    assert result["status"] == "stable"
    assert result["peak_to_average_ratio"] < 1.2


def test_volatile_activity():
    result = analyze_activity_volatility([0, 0, 1, 0, 20])
    assert result["status"] == "volatile"
    assert result["coefficient_of_variation"] > 1


def test_inactive_activity():
    assert analyze_activity_volatility([0, 0, 0])["status"] == "inactive"


def test_invalid_activity_rejected():
    with pytest.raises(ValueError):
        analyze_activity_volatility([1, -1, 2])
