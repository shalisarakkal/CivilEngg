from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from civil_engineering.config import get_settings
from civil_engineering.routes import router

settings = get_settings()
app = FastAPI(title="Civil Engineering AI API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001", "http://localhost:3002"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "environment": settings.app_env}
