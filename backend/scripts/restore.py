"""Restore the database and local file storage from a backup made by backup.py.

Restores both together, for the same reason backup.py captures both together:
a database and storage tree from different points in time can leave dangling
file references.

This is destructive. It drops and recreates objects in the target database
(pg_restore --clean --if-exists) and refuses to overwrite an existing,
non-empty local storage directory unless --force is passed.

The dump includes PostGIS's own objects (the "postgis" extension and its
spatial_ref_sys table), owned by whoever created that extension in the
source database (typically the postgres superuser, not the app's own
role). Restoring those requires connecting as that same owning role via
--pg-user; the app's normal DATABASE_URL role usually can't drop/recreate
them. Set PGPASSWORD in the environment for that role before running this.

Usage:
    uv run python scripts/restore.py backups/20260916T153000Z [--force] \
        [--pg-restore path/to/pg_restore] [--pg-user postgres]
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from civil_engineering.config import get_settings
from civil_engineering.database import engine


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup_dir", help="Backup folder created by backup.py")
    parser.add_argument(
        "--pg-restore",
        default="pg_restore",
        help="Path to the pg_restore executable if not on PATH",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing, non-empty local storage directory",
    )
    parser.add_argument(
        "--pg-user",
        help="Role to run pg_restore as (defaults to DATABASE_URL's role; use the "
        "role that owns the postgis extension, typically the postgres superuser)",
    )
    args = parser.parse_args()

    backup_dir = Path(args.backup_dir)
    dump_path = backup_dir / "database.dump"
    storage_backup = backup_dir / "storage"
    if not dump_path.exists():
        print(f"No database.dump found in {backup_dir}", file=sys.stderr)
        raise SystemExit(1)

    settings = get_settings()
    url = engine.url
    if url.get_backend_name() != "postgresql":
        print(
            f"Refusing to restore into a non-PostgreSQL DATABASE_URL ({url.drivername}).",
            file=sys.stderr,
        )
        raise SystemExit(1)

    storage_target = Path(settings.local_storage_path)
    target_has_data = storage_target.exists() and any(storage_target.iterdir())
    if storage_backup.exists() and target_has_data and not args.force:
        print(
            f"{storage_target} already exists and is not empty. "
            "Move it aside or pass --force to overwrite.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    pg_user = args.pg_user or url.username or ""
    command = [
        args.pg_restore,
        "--clean",
        "--if-exists",
        "-h",
        url.host or "localhost",
        "-p",
        str(url.port or 5432),
        "-U",
        pg_user,
        "-d",
        url.database or "",
        str(dump_path),
    ]
    env = dict(os.environ)
    if pg_user == (url.username or ""):
        # Only default PGPASSWORD from DATABASE_URL when restoring as that
        # same role. A different --pg-user (e.g. postgres) needs its own
        # password: leave PGPASSWORD unset so pg_restore prompts for it,
        # rather than silently authenticating with the wrong credential.
        env.setdefault("PGPASSWORD", url.password or "")
    subprocess.run(command, check=True, env=env)

    if storage_backup.exists():
        if target_has_data and args.force:
            shutil.rmtree(storage_target)
        shutil.copytree(storage_backup, storage_target, dirs_exist_ok=True)

    print(f"Restored database and storage from {backup_dir}")


if __name__ == "__main__":
    main()
