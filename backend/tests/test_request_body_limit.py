from fastapi.testclient import TestClient
import pytest

from app import main


client = TestClient(main.app)


@pytest.fixture(autouse=True)
def configured_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEVPULSE_MAX_REQUEST_BYTES", "160")


def test_oversized_declared_body_is_rejected_before_validation() -> None:
    response = client.post(
        "/activity/summary",
        content=b"{}",
        headers={"Content-Length": "161", "Content-Type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json() == {
        "detail": "request body exceeds configured byte limit"
    }
    assert response.headers["x-max-request-bytes"] == "160"


def test_actual_body_size_is_checked_when_declared_length_is_too_small() -> None:
    response = client.post(
        "/activity/summary",
        content=b"x" * 161,
        headers={"Content-Length": "1", "Content-Type": "application/json"},
    )

    assert response.status_code == 413
    assert response.headers["x-max-request-bytes"] == "160"


def test_body_at_limit_reaches_normal_validation() -> None:
    response = client.post(
        "/activity/summary",
        content=b"{}",
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422
    assert response.headers["x-request-id"]


@pytest.mark.parametrize("configured", ["0", "-1", "invalid"])
def test_invalid_limit_fails_safe_to_default(
    monkeypatch: pytest.MonkeyPatch,
    configured: str,
) -> None:
    monkeypatch.setenv("DEVPULSE_MAX_REQUEST_BYTES", configured)

    assert main.max_request_bytes() == main.DEFAULT_MAX_REQUEST_BYTES


def test_read_endpoints_are_not_subject_to_body_limit() -> None:
    response = client.get("/health", headers={"Content-Length": "999999"})

    assert response.status_code == 200
