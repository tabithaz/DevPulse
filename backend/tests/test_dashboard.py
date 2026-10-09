from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_dashboard_is_served() -> None:
    response = client.get("/dashboard")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "DevPulse Dashboard" in response.text
    assert 'id="repository-form"' in response.text
    assert 'id="api-key"' in response.text
    assert response.headers["content-security-policy"] == (
        "default-src 'none'; base-uri 'none'; form-action 'self'; "
        "frame-ancestors 'none'; connect-src 'self'; "
        "img-src 'self' data:; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'"
    )


def test_dashboard_integrates_with_snapshot_api() -> None:
    response = client.get("/dashboard")

    assert "/github/${owner}/${repository}/snapshots" in response.text
    assert "Collect now" in response.text
    assert "Star history" in response.text
    assert "/github/snapshots/summary" in response.text
    assert "Portfolio snapshot summary" in response.text
    assert "`${route()}/delta`" in response.text
    assert "since last snapshot" in response.text
    assert "Portfolio operational insights" in response.text
    assert 'id="growth-leaders"' in response.text
    assert 'id="portfolio-alerts"' in response.text
    assert "/github/snapshots/trends?limit=30" in response.text
    assert "/github/snapshots/alerts" in response.text
    assert "renderGrowthLeaders" in response.text
    assert "renderAlerts" in response.text
    assert "options.headers['X-API-Key'] = apiKey" in response.text
