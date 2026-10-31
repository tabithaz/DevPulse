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


@pytest.mark.parametrize("invalid", [True, False, 2.5, float("nan"), float("inf"), "3", None, 10**400])
def test_rejects_invalid_change_counts(invalid):
    with pytest.raises(ValueError, match="change counts"):
        analyze_deployment_batches([1, invalid])


@pytest.mark.parametrize("invalid", [True, False, 2.5, float("nan"), float("inf"), "20", None, 10**400])
@pytest.mark.parametrize("threshold", ["warning_size", "critical_size"])
def test_rejects_invalid_threshold_types_and_ranges(threshold, invalid):
    with pytest.raises(ValueError, match="thresholds"):
        analyze_deployment_batches([1], **{threshold: invalid})


def test_zero_counts_and_exact_threshold_boundaries():
    report = analyze_deployment_batches([0, 3, 4], warning_size=3, critical_size=5)
    assert report.total_changes == 7
    assert report.oversized_deployments == 2
    assert report.status == "high_risk"
    assert analyze_deployment_batches([0, 2, 3], warning_size=3, critical_size=5).status == "watch"
    assert analyze_deployment_batches([0, 5], warning_size=3, critical_size=5).status == "high_risk"
