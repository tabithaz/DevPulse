import pytest

from app.ownership import analyze_ownership_resilience


def test_fragile_when_one_owner_dominates():
    result = analyze_ownership_resilience({"tabitha": 80, "dev-b": 10, "dev-c": 10})
    assert result.status == "fragile"
    assert result.bus_factor == 1
    assert result.top_owner_share == 0.8


def test_resilient_when_work_is_distributed():
    result = analyze_ownership_resilience({"a": 30, "b": 25, "c": 25, "d": 20})
    assert result.status == "resilient"
    assert result.bus_factor == 3
    assert result.effective_owners > 3.5


def test_empty_activity_is_unowned():
    assert analyze_ownership_resilience({}).status == "unowned"
    assert analyze_ownership_resilience({"a": 0}).bus_factor == 0


def test_invalid_counts_are_rejected():
    with pytest.raises(ValueError):
        analyze_ownership_resilience({"a": -1})
    with pytest.raises(ValueError):
        analyze_ownership_resilience({"a": True})
