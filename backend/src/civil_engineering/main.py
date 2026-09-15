import logging
import time
from collections.abc import Awaitable, Callable
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from civil_engineering.config import get_settings
from civil_engineering.database import engine
from civil_engineering.logging_config import configure_logging, correlation_id_var
from civil_engineering.routes import router

configure_logging()
logger = logging.getLogger("civil_engineering")

MAX_JSON_BODY_BYTES = 2 * 1024 * 1024

settings = get_settings()
app = FastAPI(title="Civil Engineering AI API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)


RequestHandler = Callable[[Request], Awaitable[Response]]


@app.middleware("http")
async def correlate_and_log_requests(request: Request, call_next: RequestHandler) -> Response:
    correlation_id = request.headers.get("x-request-id") or str(uuid4())
    token = correlation_id_var.set(correlation_id)
    started = time.perf_counter()
    try:
        response = await call_next(request)
    finally:
        correlation_id_var.reset(token)
    duration_ms = (time.perf_counter() - started) * 1000
    response.headers["X-Request-ID"] = correlation_id
    logger.info(
        "%s %s -> %s (%.1fms)", request.method, request.url.path, response.status_code, duration_ms
    )
    return response


@app.middleware("http")
async def limit_request_body_size(request: Request, call_next: RequestHandler) -> Response:
    content_type = request.headers.get("content-type", "")
    content_length = request.headers.get("content-length")
    if "multipart/form-data" not in content_type and content_length is not None:
        if int(content_length) > MAX_JSON_BODY_BYTES:
            return JSONResponse(status_code=413, content={"detail": "Request body too large"})
    return await call_next(request)


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    correlation_id = correlation_id_var.get()
    logger.exception("Unhandled error handling %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "request_id": correlation_id},
        headers={"X-Request-ID": correlation_id},
    )


app.include_router(router)


@app.get("/health")
def health() -> dict[str, str]:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        database_status = "ok"
    except Exception:
        database_status = "unavailable"
    return {"status": "ok", "environment": settings.app_env, "database": database_status}
