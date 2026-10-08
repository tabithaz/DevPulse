from fastapi.testclient import TestClient

import app.main as main
from app.http_metrics import RequestMetrics, render_request_metrics


client = TestClient(main.app)


def test_request_metrics_render_red_signals() -> None:
    metrics = RequestMetrics()
    metrics.begin()
    metrics.observe("GET", "/health", 200, 0.02)
    metrics.begin()
    metrics.observe("GET", "/health", 503, 0.3)

    output = "\n".join(render_request_metrics(metrics.snapshot()))

    assert 'devpulse_http_requests_total{method="GET",route="/health",status="200"} 1' in output
    assert 'devpulse_http_requests_total{method="GET",route="/health",status="503"} 1' in output
    assert 'devpulse_http_request_duration_seconds_count{method="GET",route="/health"} 2' in output
    assert 'devpulse_http_request_duration_seconds_bucket{method="GET",route="/health",le="+Inf"} 2' in output
    assert "devpulse_http_requests_in_flight 0" in output


def test_api_metrics_use_route_templates_for_repository_paths(monkeypatch) -> None:
    metrics = RequestMetrics()
    monkeypatch.setattr(main, "request_metrics", metrics)

    response = client.get("/github/owner-a/repository-a/snapshots")
    assert response.status_code == 200
    response = client.get("/github/owner-b/repository-b/snapshots")
    assert response.status_code == 200
    output = client.get("/metrics").text

    route = "/github/{owner}/{repository}/snapshots"
    assert f'route="{route}",status="200"}} 2' in output
    assert "owner-a" not in output
    assert "repository-b" not in output


def test_unknown_paths_share_one_bounded_label(monkeypatch) -> None:
    metrics = RequestMetrics()
    monkeypatch.setattr(main, "request_metrics", metrics)

    assert client.get("/missing-one").status_code == 404
    assert client.get("/missing-two").status_code == 404
    output = client.get("/metrics").text

    assert 'route="unmatched",status="404"} 2' in output
    assert "missing-one" not in output
    assert "missing-two" not in output
