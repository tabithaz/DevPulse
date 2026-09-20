import pytest
from app.reviewer_load import analyze_reviewer_load

def test_balanced_review_load():
    report = analyze_reviewer_load([8, 10, 9, 11])
    assert report.status == "balanced"
    assert report.total_reviews == 38

def test_imbalanced_review_load_enters_watch():
    assert analyze_reviewer_load([1, 1, 1, 5]).status == "watch"

def test_concentrated_review_load_is_critical():
    assert analyze_reviewer_load([0, 0, 0, 8]).status == "critical"

def test_empty_review_load():
    assert analyze_reviewer_load([]).status == "no_data"

@pytest.mark.parametrize("values", [[-1, 2], [True, 2], ["4", 2]])
def test_invalid_review_counts(values):
    with pytest.raises(ValueError):
        analyze_reviewer_load(values)
