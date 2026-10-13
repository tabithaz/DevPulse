from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_drain_marker_fails_readiness_but_preserves_liveness(
    tmp_path,
    monkeypatch,
) -> None:
    marker = tmp_path / "draining"
    marker.touch()
    monkeypatch.setenv("DEVPULSE_DRAIN_MARKER", str(marker))

    readiness = client.get("/ready")
    liveness = client.get("/health")

    assert readiness.status_code == 503
    assert readiness.json() == {"detail": "service is draining"}
    assert readiness.headers["retry-after"] == "5"
    assert liveness.status_code == 200


def test_drain_marker_rejects_new_collection_work(tmp_path, monkeypatch) -> None:
    marker = tmp_path / "draining"
    marker.touch()
    monkeypatch.setenv("DEVPULSE_DRAIN_MARKER", str(marker))

    response = client.post(
        "/github/snapshots/collect",
        json={"repositories": [{"owner": "tabithaz", "repository": "DevPulse"}]},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "service is draining"}
    assert response.headers["retry-after"] == "5"


def test_drain_marker_preserves_read_only_analytics(tmp_path, monkeypatch) -> None:
    marker = tmp_path / "draining"
    marker.touch()
    monkeypatch.setenv("DEVPULSE_DRAIN_MARKER", str(marker))
    monkeypatch.setenv("DEVPULSE_DB_PATH", str(tmp_path / "devpulse.db"))

    response = client.get("/github/snapshots/summary")

    assert response.status_code == 200


def test_missing_drain_marker_keeps_service_ready(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DEVPULSE_DB_PATH", str(tmp_path / "devpulse.db"))
    monkeypatch.setenv("DEVPULSE_DRAIN_MARKER", str(tmp_path / "draining"))

    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "available"}
