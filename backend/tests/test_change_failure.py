import pytest

from app.change_failure import analyze_change_failure


def test_healthy_failure_rate():
    report = analyze_change_failure([True] * 9 + [False])
    assert report.failure_rate_percent == 10.0
    assert report.status == "healthy"


def test_watch_failure_rate():
    assert analyze_change_failure([True] * 4 + [False]).status == "watch"


def test_critical_failure_rate():
    assert analyze_change_failure([True, False, False]).status == "critical"


def test_empty_history_returns_no_data():
    assert analyze_change_failure([]).status == "no_data"


def test_threshold_validation():
    with pytest.raises(ValueError):
        analyze_change_failure([True], warning_percent=30, critical_percent=20)


@pytest.mark.parametrize("deployments", [[True, 1], [False, None], "success"])
def test_deployment_history_requires_boolean_list(deployments):
    with pytest.raises(ValueError, match="list of booleans"):
        analyze_change_failure(deployments)


@pytest.mark.parametrize(
    ("warning", "critical"),
    [
        (float("nan"), 30.0),
        (15.0, float("inf")),
        (True, 30.0),
        ("15", 30.0),
    ],
)
def test_thresholds_require_finite_numeric_values(warning, critical):
    with pytest.raises(ValueError, match="finite numbers"):
        analyze_change_failure([True], warning_percent=warning, critical_percent=critical)
