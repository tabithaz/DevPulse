import pytest

from app.bulkhead import InFlightLimiter


@pytest.mark.parametrize("limit", [0, -1, True, False, 1.5, "2", None])
def test_rejects_invalid_capacity_without_changing_counters(limit):
    limiter = InFlightLimiter()
    with pytest.raises(ValueError, match="limit must be a positive integer"):
        limiter.try_acquire(limit)
    with pytest.raises(ValueError, match="limit must be a positive integer"):
        limiter.snapshot(limit)
    assert limiter.snapshot(1) == {"limit": 1, "in_flight": 0, "rejected_total": 0}


def test_capacity_rejection_and_release():
    limiter = InFlightLimiter()
    assert limiter.try_acquire(1)
    assert not limiter.try_acquire(1)
    assert limiter.snapshot(1) == {"limit": 1, "in_flight": 1, "rejected_total": 1}
    limiter.release()
    assert limiter.try_acquire(1)
