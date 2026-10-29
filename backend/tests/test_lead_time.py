import math

import pytest

from app.lead_time import analyze_lead_time


def test_healthy_lead_times():
    report = analyze_lead_time([4, 8, 12, 24])
    assert report.status == "healthy"
    assert report.median_hours == 10.0
    assert report.slow_changes == 0


def test_watch_when_a_change_crosses_warning_threshold():
    report = analyze_lead_time([8, 12, 24, 60])
    assert report.status == "watch"
    assert report.slow_changes == 1


def test_critical_when_p90_crosses_critical_threshold():
    report = analyze_lead_time([8, 12, 24, 48, 144])
    assert report.status == "critical"
    assert report.p90_hours == 144.0


def test_empty_input_returns_no_data():
    assert analyze_lead_time([]).status == "no_data"


def test_rejects_invalid_inputs():

    with pytest.raises(ValueError):
        analyze_lead_time([-1])
    with pytest.raises(ValueError):
        analyze_lead_time([1], warning_hours=10, critical_hours=5)


@pytest.mark.parametrize(
    "invalid",
    [float("nan"), float("inf"), -float("inf"), True, False, "12", None, 10**400],
)
def test_rejects_invalid_lead_times(invalid):
    with pytest.raises(ValueError, match="lead times must be finite"):
        analyze_lead_time([4, invalid])


@pytest.mark.parametrize(
    "invalid",
    [float("nan"), float("inf"), -float("inf"), True, False, "24", None, 10**400],
)
@pytest.mark.parametrize("field", ["warning_hours", "critical_hours"])
def test_rejects_invalid_thresholds(field, invalid):
    with pytest.raises(ValueError, match="thresholds must be finite"):
        analyze_lead_time([1], **{field: invalid})


def test_even_median_stays_finite_for_large_lead_times():
    report = analyze_lead_time([1e308, 1e308])
    assert math.isfinite(report.median_hours)
    assert report.median_hours == 1e308
    assert report.p90_hours == 1e308
    assert report.status == "critical"


def test_zero_and_exact_threshold_boundaries():
    report = analyze_lead_time([0, 48, 120], warning_hours=48, critical_hours=120)
    assert report.median_hours == 48
    assert report.slow_changes == 2
    assert report.status == "critical"
