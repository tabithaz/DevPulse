import pytest

from app.deployment_frequency import analyze_deployment_frequency


def test_frequent_delivery():
    report = analyze_deployment_frequency([0, 1, 3, 4, 6])
    assert report.status == "frequent"
    assert report.longest_gap_days == 2


def test_steady_delivery():
    report = analyze_deployment_frequency([0, 4, 9, 15])
    assert report.status == "steady"


def test_sporadic_delivery():
    report = analyze_deployment_frequency([0, 10, 30])
    assert report.status == "sporadic"
    assert report.longest_gap_days == 20


def test_no_data_and_single_deployment():
    assert analyze_deployment_frequency([]).status == "no_data"
    assert analyze_deployment_frequency([2]).status == "insufficient_data"


def test_rejects_unsorted_days():
    with pytest.raises(ValueError):
        analyze_deployment_frequency([2, 1])


@pytest.mark.parametrize(
    "invalid",
    [float("nan"), float("inf"), -float("inf"), True, False, "3", None, 10**400],
)
def test_rejects_nonfinite_or_nonnumeric_deployment_days(invalid):
    with pytest.raises(ValueError, match="finite non-negative numbers"):
        analyze_deployment_frequency([0, invalid])


@pytest.mark.parametrize("invalid", [None, (0, 1), "0,1"])
def test_requires_list_of_deployment_days(invalid):
    with pytest.raises(ValueError, match="finite non-negative numbers"):
        analyze_deployment_frequency(invalid)


def test_same_day_deployments_remain_supported():
    report = analyze_deployment_frequency([0, 0, 1])
    assert report.deployment_count == 3
    assert report.status == "frequent"
    assert report.longest_gap_days == 1
