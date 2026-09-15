"""Create the SQLite schema and storage directory for local Playwright e2e runs.

Reads DATABASE_URL and LOCAL_STORAGE_PATH from the environment (set by
frontend/playwright.config.ts) rather than hardcoding paths, so it works
regardless of the checkout location.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from civil_engineering import models  # noqa: F401
from civil_engineering.config import get_settings
from civil_engineering.database import Base, engine

if __name__ == "__main__":
    database_path = engine.url.database
    if database_path:
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)
    Path(get_settings().local_storage_path).mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)
    print("e2e database ready")
