from fastapi.testclient import TestClient

from civil_engineering.main import app

client = TestClient(app)


def test_health_returns_ok() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] in {"ok", "unavailable"}
