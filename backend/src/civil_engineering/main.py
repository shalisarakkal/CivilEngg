from fastapi import FastAPI

from civil_engineering.config import get_settings

settings = get_settings()
app = FastAPI(title="Civil Engineering AI API", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "environment": settings.app_env}
