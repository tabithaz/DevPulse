import gzip

from fastapi.testclient import TestClient

from app.main import app


def test_large_api_responses_support_gzip_compression() -> None:
    with TestClient(app) as client:
        request = client.build_request(
            "GET",
            "/openapi.json",
            headers={"Accept-Encoding": "gzip"},
        )
        response = client.send(request, stream=True)
        compressed = b"".join(response.iter_raw())

    decoded = gzip.decompress(compressed)
    assert response.status_code == 200
    assert response.headers["content-encoding"] == "gzip"
    assert response.headers["vary"] == "Accept-Encoding"
    assert len(compressed) < len(decoded)
    assert decoded.startswith(b'{"openapi"')


def test_small_health_response_is_not_compressed() -> None:
    with TestClient(app) as client:
        response = client.get("/health", headers={"Accept-Encoding": "gzip"})

    assert response.status_code == 200
    assert "content-encoding" not in response.headers
