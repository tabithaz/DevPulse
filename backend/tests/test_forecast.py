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


def test_forecast_handles_zero_baseline_without_division_error():
    result = forecast_activity([0, 5])

    assert result.momentum_percent == 100.0


@pytest.mark.parametrize("windows", [[], [1, -1]])
def test_forecast_rejects_invalid_windows(windows):
    with pytest.raises(ValueError):
        forecast_activity(windows)
