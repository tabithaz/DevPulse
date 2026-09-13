import pytest

from app.delivery import analyze_delivery_readiness


def test_ready_portfolio():
    result = analyze_delivery_readiness(1.0, 90, 0, 14)
    assert result.status == "ready"
    assert result.score == 97.0
    assert result.blockers == ()


def test_critical_issue_blocks_release():
    result = analyze_delivery_readiness(1.0, 100, 2, 14)
    assert result.status == "blocked"
    assert "critical_issues" in result.blockers


def test_review_state_for_marginal_readiness():
    result = analyze_delivery_readiness(0.98, 75, 0, 7)
    assert result.status == "review"


def test_invalid_pass_rate_is_rejected():
    with pytest.raises(ValueError):
        analyze_delivery_readiness(1.1, 80, 0, 1)
