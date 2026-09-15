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
