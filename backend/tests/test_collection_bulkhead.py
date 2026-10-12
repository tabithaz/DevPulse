from fastapi.testclient import TestClient

import app.main as main
from app.bulkhead import InFlightLimiter


client = TestClient(main.app)


def test_saturated_collection_fails_fast(monkeypatch) -> None:
    limiter = InFlightLimiter()
    assert limiter.try_acquire(1)
    monkeypatch.setattr(main, "collection_limiter", limiter)
    monkeypatch.setenv("DEVPULSE_MAX_CONCURRENT_COLLECTIONS", "1")

    response = client.post(
        "/github/snapshots/collect",
        json={"repositories": [{"owner": "tabithaz", "repository": "DevPulse"}]},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "collection concurrency limit reached"}
    assert response.headers["retry-after"] == "1"
    assert response.headers["x-concurrency-limit"] == "1"
    assert limiter.snapshot(1)["rejected_total"] == 1
    limiter.release()


def test_non_collection_routes_do_not_consume_capacity(monkeypatch) -> None:
    limiter = InFlightLimiter()
    assert limiter.try_acquire(1)
    monkeypatch.setattr(main, "collection_limiter", limiter)
    monkeypatch.setenv("DEVPULSE_MAX_CONCURRENT_COLLECTIONS", "1")

    response = client.get("/health")

    assert response.status_code == 200
    assert limiter.snapshot(1)["rejected_total"] == 0
    limiter.release()


def test_collection_capacity_is_released_after_failure(monkeypatch) -> None:
    limiter = InFlightLimiter()
    monkeypatch.setattr(main, "collection_limiter", limiter)
    monkeypatch.setenv("DEVPULSE_MAX_CONCURRENT_COLLECTIONS", "1")
    monkeypatch.setenv("DEVPULSE_API_KEY", "required-key")

    response = client.post(
        "/github/snapshots/collect",
        json={"repositories": [{"owner": "tabithaz", "repository": "DevPulse"}]},
    )

    assert response.status_code == 401
    assert limiter.snapshot(1)["in_flight"] == 0


def test_metrics_expose_collection_bulkhead(monkeypatch, tmp_path) -> None:
    limiter = InFlightLimiter()
    assert limiter.try_acquire(3)
    monkeypatch.setattr(main, "collection_limiter", limiter)
    monkeypatch.setenv("DEVPULSE_MAX_CONCURRENT_COLLECTIONS", "3")
    monkeypatch.setenv("DEVPULSE_DB_PATH", str(tmp_path / "metrics.db"))

    response = client.get("/metrics")

    assert response.status_code == 200
    assert "devpulse_collection_concurrency_limit 3" in response.text
    assert "devpulse_collection_requests_in_flight 1" in response.text
    assert "devpulse_collection_requests_rejected_total 0" in response.text
    limiter.release()
