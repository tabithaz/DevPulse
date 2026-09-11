import pytest

from app.trends import analyze_activity_trend


def test_activity_trend_increase():
    result = analyze_activity_trend(20, 30)
    assert result.direction == "increasing"
    assert result.delta == 10
    assert result.percent_change == 50.0


def test_activity_trend_decrease():
    result = analyze_activity_trend(40, 10)
    assert result.direction == "decreasing"
    assert result.delta == -30
    assert result.percent_change == -75.0


def test_activity_trend_zero_baseline_has_no_percentage():
    result = analyze_activity_trend(0, 7)
    assert result.direction == "increasing"
    assert result.delta == 7
    assert result.percent_change is None


def test_activity_trend_zero_to_zero_is_stable():
    result = analyze_activity_trend(0, 0)
    assert result.direction == "steady"
    assert result.delta == 0
    assert result.percent_change == 0.0


def test_activity_trend_rejects_negative_counts():
    with pytest.raises(ValueError):
        analyze_activity_trend(-1, 4)
