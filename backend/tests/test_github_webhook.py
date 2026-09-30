import hashlib
import hmac
import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from app.github_client import RepositorySnapshot, github_client_dependency
from app.main import app
from app.snapshot_store import SnapshotStore, snapshot_store_dependency


client = TestClient(app)
SECRET = "portfolio-webhook-secret"


class WebhookGitHubClient:
    def __init__(self) -> None:
        self.calls = 0

    def repository_snapshot(self, owner: str, repository: str) -> RepositorySnapshot:
        self.calls += 1
        return RepositorySnapshot(
            repository=f"{owner}/{repository}",
            description="Webhook repository",
            default_branch="main",
            language="Python",
            stars=24,
            forks=5,
            open_issues=3,
            archived=False,
            created_at="2025-01-01T00:00:00Z",
            pushed_at="2026-09-30T15:00:00Z",
            collected_at="2026-09-30T16:00:00+00:00",
        )


def signed_headers(body: bytes, delivery: str = "delivery-001", event: str = "push") -> dict:
    signature = "sha256=" + hmac.new(
        SECRET.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-GitHub-Event": event,
        "X-GitHub-Delivery": delivery,
        "X-Hub-Signature-256": signature,
    }


@pytest.fixture
def webhook_dependencies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    github = WebhookGitHubClient()
    store = SnapshotStore(tmp_path / "webhooks.db")
    app.dependency_overrides[github_client_dependency] = lambda: github
    app.dependency_overrides[snapshot_store_dependency] = lambda: store
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    try:
        yield github, store
    finally:
        app.dependency_overrides.clear()


def webhook_body(repository: str = "tabithaz/DevPulse") -> bytes:
    return json.dumps({"repository": {"full_name": repository}}).encode("utf-8")


def test_signed_push_collects_snapshot_and_replays_delivery(webhook_dependencies) -> None:
    github, store = webhook_dependencies
    body = webhook_body()
    headers = signed_headers(body)

    first = client.post("/github/webhooks", content=body, headers=headers)
    replay = client.post("/github/webhooks", content=body, headers=headers)

    assert first.status_code == replay.status_code == 202
    assert first.json() == replay.json()
    assert first.json()["status"] == "collected"
    assert first.json()["repository"]["repository"] == "tabithaz/DevPulse"
    assert first.headers["idempotency-replayed"] == "false"
    assert replay.headers["idempotency-replayed"] == "true"
    assert github.calls == 1
    assert len(store.history("tabithaz/DevPulse")) == 1


def test_invalid_signature_cannot_collect(webhook_dependencies) -> None:
    github, store = webhook_dependencies
    body = webhook_body()
    headers = signed_headers(body)
    headers["X-Hub-Signature-256"] = "sha256=" + "0" * 64

    response = client.post("/github/webhooks", content=body, headers=headers)

    assert response.status_code == 401
    assert github.calls == 0
    assert store.history("tabithaz/DevPulse") == []


def test_missing_secret_disables_webhook(webhook_dependencies, monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET")
    body = webhook_body()

    response = client.post("/github/webhooks", content=body, headers=signed_headers(body))

    assert response.status_code == 503
    assert response.json() == {"detail": "GitHub webhook is not configured"}


def test_ping_and_unsupported_events_do_not_call_github(webhook_dependencies) -> None:
    github, _store = webhook_dependencies
    body = webhook_body()

    ping = client.post(
        "/github/webhooks",
        content=body,
        headers=signed_headers(body, delivery="ping-001", event="ping"),
    )
    issues = client.post(
        "/github/webhooks",
        content=body,
        headers=signed_headers(body, delivery="issues-001", event="issues"),
    )

    assert ping.status_code == issues.status_code == 202
    assert ping.json() == {"status": "pong"}
    assert issues.json() == {"status": "ignored", "event": "issues"}
    assert github.calls == 0


def test_delivery_id_cannot_be_reused_for_different_payload(webhook_dependencies) -> None:
    github, _store = webhook_dependencies
    first_body = webhook_body("tabithaz/DevPulse")
    second_body = webhook_body("tabithaz/TelemetryGuard")

    first = client.post(
        "/github/webhooks",
        content=first_body,
        headers=signed_headers(first_body, delivery="delivery-conflict"),
    )
    conflict = client.post(
        "/github/webhooks",
        content=second_body,
        headers=signed_headers(second_body, delivery="delivery-conflict"),
    )

    assert first.status_code == 202
    assert conflict.status_code == 409
    assert "different request" in conflict.json()["detail"]
    assert github.calls == 1


@pytest.mark.parametrize(
    "payload",
    [{}, {"repository": {}}, {"repository": {"full_name": "invalid"}}],
)
def test_invalid_repository_payload_is_rejected(webhook_dependencies, payload: dict) -> None:
    body = json.dumps(payload).encode("utf-8")
    response = client.post("/github/webhooks", content=body, headers=signed_headers(body))

    assert response.status_code == 422
    assert response.json() == {"detail": "webhook repository is invalid"}


def test_non_object_payload_is_rejected(webhook_dependencies) -> None:
    body = b"[]"
    response = client.post("/github/webhooks", content=body, headers=signed_headers(body))

    assert response.status_code == 400
    assert response.json() == {"detail": "invalid GitHub webhook payload"}
