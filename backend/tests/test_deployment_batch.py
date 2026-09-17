import pytest

from app.deployment_batch import analyze_deployment_batches


def test_small_batches_are_healthy():
    report = analyze_deployment_batches([3, 5, 8, 10])
    assert report.median_batch_size == 6.5
    assert report.largest_batch_size == 10
    assert report.status == "healthy"


def test_single_oversized_batch_is_watch():
    report = analyze_deployment_batches([4, 6, 22, 8])
    assert report.oversized_deployments == 1
    assert report.status == "watch"


def test_many_large_batches_are_high_risk():
    report = analyze_deployment_batches([25, 30, 5, 7])
    assert report.status == "high_risk"


def test_critical_batch_is_high_risk():
    assert analyze_deployment_batches([2, 55, 3]).status == "high_risk"


def test_empty_history():
    assert analyze_deployment_batches([]).status == "no_data"


def test_rejects_invalid_input():
    with pytest.raises(ValueError):
        analyze_deployment_batches([1, -1])
