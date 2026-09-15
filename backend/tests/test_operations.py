import json

import anyio
from fastapi.testclient import TestClient
from starlette.requests import Request

from civil_engineering.logging_config import correlation_id_var
from civil_engineering.main import MAX_JSON_BODY_BYTES, app, handle_unexpected_error

client = TestClient(app)


def test_responses_carry_a_correlation_id_header() -> None:
    response = client.get("/health")

    assert "X-Request-ID" in response.headers


def test_client_supplied_correlation_id_is_echoed_back() -> None:
    response = client.get("/health", headers={"X-Request-ID": "test-correlation-id"})

    assert response.headers["X-Request-ID"] == "test-correlation-id"


def test_oversized_json_body_is_rejected() -> None:
    oversized_name = "a" * (MAX_JSON_BODY_BYTES + 1)

    response = client.post(
        "/clients",
        content=json.dumps({"name": oversized_name}),
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 413


def test_unhandled_exception_handler_returns_json_with_request_id() -> None:
    async def run() -> None:
        scope = {"type": "http", "method": "GET", "path": "/boom", "headers": []}
        request = Request(scope)
        token = correlation_id_var.set("boom-correlation-id")
        try:
            response = await handle_unexpected_error(request, RuntimeError("boom"))
        finally:
            correlation_id_var.reset(token)
        assert response.status_code == 500
        body = json.loads(bytes(response.body))
        assert body["request_id"] == "boom-correlation-id"
        assert "boom" not in body["detail"]

    anyio.run(run)
