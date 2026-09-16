"""Back up the application database and local file storage together.

They must be restored together: SourceFile rows reference paths under
LOCAL_STORAGE_PATH, so a database from one point in time paired with storage
from another can leave dangling references. See restore.py.

Usage:
    uv run python scripts/backup.py [--out-dir backups] [--pg-dump path/to/pg_dump]
"""

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from civil_engineering.config import get_settings
from civil_engineering.database import engine


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir", default="backups", help="Directory to create the timestamped backup folder in"
    )
    parser.add_argument(
        "--pg-dump", default="pg_dump", help="Path to the pg_dump executable if not on PATH"
    )
    args = parser.parse_args()

    settings = get_settings()
    url = engine.url
    if url.get_backend_name() != "postgresql":
        print(
            f"Refusing to back up a non-PostgreSQL DATABASE_URL ({url.drivername}); "
            "this backs up real application data, not the automated test database.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = Path(args.out_dir) / timestamp
    backup_dir.mkdir(parents=True, exist_ok=False)

    dump_path = backup_dir / "database.dump"
    command = [
        args.pg_dump,
        "-Fc",
        "-h",
        url.host or "localhost",
        "-p",
        str(url.port or 5432),
        "-U",
        url.username or "",
        "-d",
        url.database or "",
        "-f",
        str(dump_path),
    ]
    env = {**os.environ, "PGPASSWORD": url.password or ""}
    subprocess.run(command, check=True, env=env)

    storage_source = Path(settings.local_storage_path)
    if storage_source.exists():
        shutil.copytree(storage_source, backup_dir / "storage")
    else:
        print(f"Note: local storage path {storage_source} does not exist yet; nothing to copy.")

    print(f"Backup written to {backup_dir}")


if __name__ == "__main__":
    main()
