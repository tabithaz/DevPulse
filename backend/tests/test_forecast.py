import pytest

from app.forecast import forecast_activity


def test_forecast_weights_recent_windows_more_heavily():
    result = forecast_activity([10, 20, 30])

    assert result.forecast_events == 23
    assert result.momentum_percent == 50.0
    assert result.confidence == "medium"


def test_forecast_reports_high_confidence_with_four_windows():
    result = forecast_activity([8, 8, 8, 8])

    assert result.forecast_events == 8
    assert result.momentum_percent == 0.0
    assert result.confidence == "high"


def test_forecast_reports_undefined_momentum_without_comparison_window():
    result = forecast_activity([5])

    assert result.momentum_percent is None


def test_forecast_reports_undefined_momentum_from_zero_baseline():
    result = forecast_activity([0, 5])

    assert result.momentum_percent is None


def test_forecast_reports_zero_momentum_for_zero_to_zero():
    result = forecast_activity([0, 0])

    assert result.momentum_percent == 0.0


@pytest.mark.parametrize("windows", [[], [1, -1]])
def test_forecast_rejects_invalid_windows(windows):
    with pytest.raises(ValueError):
        forecast_activity(windows)
