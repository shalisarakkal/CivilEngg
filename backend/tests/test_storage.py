from pathlib import Path

import pytest
from pytest import MonkeyPatch

from civil_engineering import storage


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path: Path, monkeypatch: MonkeyPatch) -> Path:
    monkeypatch.setenv("LOCAL_STORAGE_PATH", str(tmp_path))
    from civil_engineering.config import get_settings

    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def test_validate_filename_rejects_path_traversal() -> None:
    with pytest.raises(storage.FileValidationError):
        storage.validate_filename("../../etc/passwd.txt")


def test_validate_filename_rejects_absolute_path() -> None:
    with pytest.raises(storage.FileValidationError):
        storage.validate_filename("/etc/passwd.csv")


def test_validate_filename_rejects_unsupported_extension() -> None:
    with pytest.raises(storage.FileValidationError):
        storage.validate_filename("payload.exe")


def test_validate_filename_accepts_a_plain_supported_name() -> None:
    assert storage.validate_filename("survey.csv") == "survey.csv"


def test_remove_file_refuses_a_path_outside_storage_root(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.csv"
    outside.write_text("data")
    try:
        with pytest.raises(storage.FileValidationError):
            storage.remove_file(str(outside))
    finally:
        outside.unlink(missing_ok=True)


def test_archive_file_refuses_a_path_outside_storage_root(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.csv"
    outside.write_text("data")
    try:
        with pytest.raises(storage.FileValidationError):
            storage.archive_file(str(outside), "project-1", "file-1")
    finally:
        outside.unlink(missing_ok=True)


def test_restore_file_refuses_a_path_outside_storage_root(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.csv"
    outside.write_text("data")
    try:
        with pytest.raises(storage.FileValidationError):
            storage.restore_file(str(outside), "project-1", "file-1", ".csv")
    finally:
        outside.unlink(missing_ok=True)


class _FakeUploadFile:
    def __init__(self, filename: str, content_type: str, chunks: list[bytes]) -> None:
        self.filename = filename
        self.content_type = content_type
        self._chunks = iter(chunks)

    async def read(self, _size: int) -> bytes:
        return next(self._chunks, b"")


async def _upload(chunks: list[bytes]) -> tuple[Path, int, str]:
    upload = _FakeUploadFile("survey.csv", "text/csv", chunks)
    return await storage.save_upload(upload, "project-1", "file-1")


def test_save_upload_rejects_files_larger_than_the_configured_limit(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(storage, "MAX_FILE_SIZE", 10)
    import anyio

    with pytest.raises(storage.FileValidationError):
        anyio.run(_upload, [b"x" * 6, b"x" * 6])


def test_save_upload_rejects_empty_files() -> None:
    import anyio

    with pytest.raises(storage.FileValidationError):
        anyio.run(_upload, [b""])
