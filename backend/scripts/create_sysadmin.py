"""Create the initial 'sysadmin' admin account and backfill ownerless projects.

Run once, after `npm run db:upgrade` applies migration 0017, before first use.
No-op (besides the backfill check) if 'sysadmin' already exists.

The initial password is read from the SYSADMIN_INITIAL_PASSWORD environment
variable -- never a CLI argument (visible in shell history/process lists) and
never hardcoded, matching this project's "no secrets in git" discipline.

Usage:
    SYSADMIN_INITIAL_PASSWORD=... uv run python scripts/create_sysadmin.py
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sqlalchemy import select

from civil_engineering.auth import ROLE_ADMIN, ROLE_POWER_USER, hash_password
from civil_engineering.database import SessionLocal
from civil_engineering.models import Project, User

SYSADMIN_USERNAME = "sysadmin"


def main() -> None:
    password = os.environ.get("SYSADMIN_INITIAL_PASSWORD")
    if not password:
        print(
            "SYSADMIN_INITIAL_PASSWORD is not set. Set it to the sysadmin account's initial "
            "password and re-run, e.g.:\n"
            "  SYSADMIN_INITIAL_PASSWORD=... uv run python scripts/create_sysadmin.py",
            file=sys.stderr,
        )
        raise SystemExit(1)

    database = SessionLocal()
    try:
        sysadmin = database.execute(
            select(User).where(User.username == SYSADMIN_USERNAME)
        ).scalar_one_or_none()
        if sysadmin is None:
            sysadmin = User(
                username=SYSADMIN_USERNAME,
                password_hash=hash_password(password),
                role=ROLE_ADMIN,
            )
            database.add(sysadmin)
            database.commit()
            database.refresh(sysadmin)
            print(f"Created '{SYSADMIN_USERNAME}' (admin).")
        else:
            print(f"'{SYSADMIN_USERNAME}' already exists; leaving it unchanged.")

        ownerless = (
            database.execute(select(Project).where(Project.owner_id.is_(None))).scalars().all()
        )
        if ownerless:
            for project in ownerless:
                project.owner_id = sysadmin.id
            database.commit()
            print(
                f"Backfilled {len(ownerless)} pre-existing project(s) with no owner onto "
                f"'{SYSADMIN_USERNAME}'. Reassign real ownership to a {ROLE_POWER_USER} account "
                "via PATCH /projects/{id}/owner once one exists."
            )
    finally:
        database.close()


if __name__ == "__main__":
    main()
