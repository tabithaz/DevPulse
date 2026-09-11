import pytest

from app.cadence import analyze_cadence


def test_steady_cadence():
    result = analyze_cadence([4, 5, 4, 6, 5, 4, 5])
    assert result["stability"] == "steady"
    assert result["active_day_percentage"] == 100.0


def test_variable_cadence():
    result = analyze_cadence([0, 2, 5, 0, 3, 6, 2])
    assert result["stability"] == "variable"
    assert result["active_days"] == 5


def test_bursty_cadence():
    result = analyze_cadence([0, 0, 0, 12, 0, 1, 0])
    assert result["stability"] == "bursty"


def test_inactive_cadence():
    result = analyze_cadence([0, 0, 0])
    assert result["stability"] == "inactive"
    assert result["coefficient_of_variation"] == 0.0


@pytest.mark.parametrize("values", [[], [1, -1], [1, 2.5]])
def test_invalid_cadence_input(values):
    with pytest.raises(ValueError):
        analyze_cadence(values)
