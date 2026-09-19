import pytest

from app.deployment_rollback import analyze_rollbacks


def test_healthy_deployment_history():
    report = analyze_rollbacks([True] * 9 + [False])
    assert report.rollbacks == 1
    assert report.rollback_rate_percent == 10.0
    assert report.status == "watch"


def test_consecutive_rollbacks_are_critical():
    report = analyze_rollbacks([True, False, False, True])
    assert report.consecutive_rollbacks == 2
    assert report.status == "critical"


def test_high_rollback_rate_is_critical():
    report = analyze_rollbacks([True, False, True, False])
    assert report.rollback_rate_percent == 50.0
    assert report.status == "critical"


def test_no_data():
    assert analyze_rollbacks([]).status == "no_data"


def test_invalid_thresholds():
    with pytest.raises(ValueError):
        analyze_rollbacks([True], warning_percent=20, critical_percent=10)
