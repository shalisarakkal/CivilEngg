"""Create the initial 'sysadmin' admin account, the default tenant, and
backfill ownerless projects / tenant-less rows.

Run once, after `npm run db:upgrade` applies the latest migrations, before
first use. No-op (besides the backfill checks) if 'sysadmin'/the default
tenant already exist.

The initial password is read from the SYSADMIN_INITIAL_PASSWORD environment
variable -- never a CLI argument (visible in shell history/process lists) and
never hardcoded, matching this project's "no secrets in git" discipline.
SYSADMIN_EMAIL is required alongside it: login is by email, not username
(PLAN.md Phase 16 -- username is only unique per tenant, so it can no longer
say by itself which tenant's user is meant).

The default tenant (DECISIONS.md ADR-010, PLAN.md Phase 16) is what makes a
dedicated single-customer install a valid, if trivial, case of the same
tenant model a shared instance uses: every pre-existing user/client/project
is backfilled onto it, so the install behaves exactly as it did before this
existed. Nothing yet reads or enforces tenant_id on any query -- this script
only establishes the row, it doesn't turn on isolation.

Usage:
    SYSADMIN_INITIAL_PASSWORD=... SYSADMIN_EMAIL=... uv run python scripts/create_sysadmin.py
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sqlalchemy import select

from civil_engineering.auth import ROLE_ADMIN, ROLE_POWER_USER, hash_password
from civil_engineering.database import SessionLocal
from civil_engineering.models import Client, Project, Tenant, User

SYSADMIN_USERNAME = "sysadmin"
DEFAULT_TENANT_NAME = "Default"


def main() -> None:
    password = os.environ.get("SYSADMIN_INITIAL_PASSWORD")
    email = os.environ.get("SYSADMIN_EMAIL")
    if not password or not email:
        print(
            "SYSADMIN_INITIAL_PASSWORD and SYSADMIN_EMAIL must both be set. Set them to the "
            "sysadmin account's initial password and login email, then re-run, e.g.:\n"
            "  SYSADMIN_INITIAL_PASSWORD=... SYSADMIN_EMAIL=... "
            "uv run python scripts/create_sysadmin.py",
            file=sys.stderr,
        )
        raise SystemExit(1)
    email = email.lower()

    database = SessionLocal()
    try:
        sysadmin = database.execute(
            select(User).where(User.username == SYSADMIN_USERNAME)
        ).scalar_one_or_none()
        if sysadmin is None:
            sysadmin = User(
                username=SYSADMIN_USERNAME,
                email=email,
                password_hash=hash_password(password),
                role=ROLE_ADMIN,
            )
            database.add(sysadmin)
            database.commit()
            database.refresh(sysadmin)
            print(f"Created '{SYSADMIN_USERNAME}' (admin, {email}).")
        elif sysadmin.email is None:
            # Re-run after upgrading from a pre-email install: backfill it,
            # since login now requires one and this account would otherwise
            # be permanently locked out.
            sysadmin.email = email
            database.commit()
            print(
                f"Backfilled '{SYSADMIN_USERNAME}'s email ({email}); "
                "leaving it unchanged otherwise."
            )
        else:
            print(f"'{SYSADMIN_USERNAME}' already exists; leaving it unchanged.")

        default_tenant = database.execute(
            select(Tenant).where(Tenant.name == DEFAULT_TENANT_NAME)
        ).scalar_one_or_none()
        if default_tenant is None:
            default_tenant = Tenant(name=DEFAULT_TENANT_NAME)
            database.add(default_tenant)
            database.commit()
            database.refresh(default_tenant)
            print(f"Created the '{DEFAULT_TENANT_NAME}' tenant.")
        else:
            print(f"'{DEFAULT_TENANT_NAME}' tenant already exists; leaving it unchanged.")

        tenantless_count = 0
        for model in (User, Client, Project):
            tenantless = (
                database.execute(select(model).where(model.tenant_id.is_(None))).scalars().all()
            )
            for row in tenantless:
                row.tenant_id = default_tenant.id
            tenantless_count += len(tenantless)
        if tenantless_count:
            database.commit()
            print(
                f"Backfilled {tenantless_count} pre-existing row(s) onto the "
                f"'{DEFAULT_TENANT_NAME}' tenant."
            )

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
