import pytest

from app.queue_tail import analyze_queue_tail


def test_healthy_tail():
    report = analyze_queue_tail([5, 10, 20])
    assert report.status == "healthy"
    assert report.p95_wait_minutes == 20.0


def test_watch_tail():
    report = analyze_queue_tail([5, 50, 60])
    assert report.status == "watch"
    assert report.over_warning == 2


def test_critical_tail():
    report = analyze_queue_tail([5, 10, 150])
    assert report.status == "critical"
    assert report.over_critical == 1


def test_empty_queue():
    assert analyze_queue_tail([]).status == "no_data"


def test_rejects_invalid_input():
    with pytest.raises(ValueError):
        analyze_queue_tail([-1])
