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


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -float("inf"), True, False, "12", None, 10**400])
def test_rejects_invalid_wait_times(invalid):
    with pytest.raises(ValueError):
        analyze_queue_tail([5, invalid])


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -float("inf"), True, False, "45", None, 10**400])
def test_rejects_invalid_warning_threshold(invalid):
    with pytest.raises(ValueError):
        analyze_queue_tail([10], warning_minutes=invalid)


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -float("inf"), True, False, "120", None, 10**400])
def test_rejects_invalid_critical_threshold(invalid):
    with pytest.raises(ValueError):
        analyze_queue_tail([10], critical_minutes=invalid)


@pytest.mark.parametrize("size, expected", [(1, 1), (20, 19), (21, 20), (100, 95)])
def test_nearest_rank_p95_boundary(size, expected):
    report = analyze_queue_tail(list(range(1, size + 1)), warning_minutes=1000, critical_minutes=2000)
    assert report.p95_wait_minutes == expected


def test_zero_wait_is_valid():
    report = analyze_queue_tail([0, 1])
    assert report.queued_changes == 2
    assert report.status == "healthy"
