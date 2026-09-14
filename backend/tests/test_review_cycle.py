import pytest
from backend.app.review_cycle import analyze_review_cycle


def test_healthy_review_cycle():
    result = analyze_review_cycle([2, 4, 8, 12], sla_hours=24)
    assert result.status == "healthy"
    assert result.median_hours_to_first_review == 6.0
    assert result.sla_breaches == 0


def test_watch_when_some_reviews_miss_sla():
    result = analyze_review_cycle([4, 8, 12, 30], sla_hours=24)
    assert result.status == "watch"
    assert result.sla_breach_rate == 0.25


def test_slow_when_breach_rate_is_high():
    result = analyze_review_cycle([8, 30, 40, 50, 60], sla_hours=24)
    assert result.status == "slow"
    assert result.p90_hours_to_first_review == 60.0


def test_empty_and_invalid_inputs():
    assert analyze_review_cycle([]).status == "no_data"
    with pytest.raises(ValueError):
        analyze_review_cycle([1, -1])
    with pytest.raises(ValueError):
        analyze_review_cycle([1, 2], sla_hours=0)
