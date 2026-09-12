import pytest

from app.workload import analyze_workload_balance


def test_balanced_workload_scores_high():
    result = analyze_workload_balance([10, 11, 9])
    assert result.classification == "balanced"
    assert result.balance_score == 90.0
    assert result.mean_events == 10.0


def test_skewed_workload_identifies_large_deviation():
    result = analyze_workload_balance([30, 5, 5])
    assert result.classification == "skewed"
    assert result.max_deviation_percent == 125.0
    assert result.balance_score == 0.0


def test_empty_and_zero_activity_are_handled():
    assert analyze_workload_balance([]).classification == "empty"
    assert analyze_workload_balance([0, 0]).classification == "balanced"


def test_negative_counts_are_rejected():
    with pytest.raises(ValueError):
        analyze_workload_balance([4, -1])
