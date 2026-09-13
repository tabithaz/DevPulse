import pytest

from app.contributors import analyze_contributor_concentration


def test_even_contributions_are_distributed():
    result = analyze_contributor_concentration([10, 10, 10, 10])
    assert result["status"] == "distributed"
    assert result["top_contributor_share"] == 0.25
    assert result["effective_contributors"] == 4.0


def test_dominant_contributor_is_concentrated():
    result = analyze_contributor_concentration([80, 10, 5, 5])
    assert result["status"] == "concentrated"
    assert result["top_contributor_share"] == 0.8
    assert result["effective_contributors"] < 2


def test_inactive_team_is_reported():
    result = analyze_contributor_concentration([0, 0, 0])
    assert result["status"] == "inactive"
    assert result["active_contributors"] == 0


def test_negative_counts_are_rejected():
    with pytest.raises(ValueError):
        analyze_contributor_concentration([5, -1, 3])
