"""Create the SQLite schema, storage directory, and role accounts for local
Playwright e2e runs.

Reads DATABASE_URL and LOCAL_STORAGE_PATH from the environment (set by
frontend/playwright.config.ts) rather than hardcoding paths, so it works
regardless of the checkout location.

Seeds one fixed-credential account per role (Admin/Power User/User) so
frontend/global-setup.ts can log in via the API and save a storageState
for the real-backend specs (full-workflow.spec.ts, phase9.spec.ts) without
each test needing its own UI login step. Fine to hardcode a plaintext
password here -- this only ever runs against the disposable, gitignored
e2e SQLite database, recreated fresh per run, never a real deployment.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from civil_engineering import models  # noqa: F401
from civil_engineering.auth import ROLE_ADMIN, ROLE_POWER_USER, ROLE_USER, hash_password
from civil_engineering.config import get_settings
from civil_engineering.database import Base, SessionLocal, engine
from civil_engineering.models import User

# Keep in sync with frontend/global-setup.ts's E2E_PASSWORD.
E2E_PASSWORD = "e2e-fixed-password-1"
E2E_ACCOUNTS = (
    ("e2e-admin", ROLE_ADMIN),
    ("e2e-power-user", ROLE_POWER_USER),
    ("e2e-user", ROLE_USER),
)


def seed_accounts() -> None:
    database = SessionLocal()
    try:
        for username, role in E2E_ACCOUNTS:
            if database.query(User).filter(User.username == username).first() is not None:
                continue
            database.add(
                User(username=username, password_hash=hash_password(E2E_PASSWORD), role=role)
            )
        database.commit()
    finally:
        database.close()


if __name__ == "__main__":
    database_path = engine.url.database
    if database_path:
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)
    Path(get_settings().local_storage_path).mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)
    seed_accounts()
    print("e2e database ready")
