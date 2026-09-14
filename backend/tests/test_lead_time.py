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
    import pytest

    with pytest.raises(ValueError):
        analyze_lead_time([-1])
    with pytest.raises(ValueError):
        analyze_lead_time([1], warning_hours=10, critical_hours=5)
