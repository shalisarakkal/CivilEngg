from hashlib import sha256
from pathlib import Path

from fastapi import UploadFile

from civil_engineering.config import get_settings

ALLOWED_EXTENSIONS = {".pdf", ".dxf", ".csv", ".txt"}
MAX_FILE_SIZE = 50 * 1024 * 1024


class FileValidationError(ValueError):
    pass


def storage_root() -> Path:
    root = Path(get_settings().local_storage_path).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def validate_filename(filename: str) -> str:
    safe_name = Path(filename).name
    if not safe_name or safe_name != filename or safe_name in {".", ".."}:
        raise FileValidationError("Invalid filename")
    if Path(safe_name).suffix.lower() not in ALLOWED_EXTENSIONS:
        raise FileValidationError("Unsupported file type")
    return safe_name


async def save_upload(upload: UploadFile, project_id: str, file_id: str) -> tuple[Path, int, str]:
    filename = validate_filename(upload.filename or "")
    extension = Path(filename).suffix.lower()
    if upload.content_type and not _content_type_matches(extension, upload.content_type):
        raise FileValidationError("File type does not match its content type")

    directory = storage_root() / project_id
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{file_id}{extension}"
    digest = sha256()
    size = 0

    try:
        with destination.open("wb") as output:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_FILE_SIZE:
                    raise FileValidationError("File exceeds the 50 MB limit")
                digest.update(chunk)
                output.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise

    if size == 0:
        destination.unlink(missing_ok=True)
        raise FileValidationError("Empty files are not supported")
    return destination, size, digest.hexdigest()


def _content_type_matches(extension: str, content_type: str) -> bool:
    accepted = {
        ".pdf": {"application/pdf", "application/octet-stream"},
        ".dxf": {"application/dxf", "application/octet-stream", "text/plain"},
        ".csv": {"text/csv", "application/csv", "text/plain", "application/octet-stream"},
        ".txt": {"text/plain", "application/octet-stream"},
    }
    return content_type.lower() in accepted[extension]


def remove_file(stored_path: str) -> None:
    path = Path(stored_path).resolve()
    root = storage_root()
    if root not in path.parents:
        raise FileValidationError("Stored path is outside local storage")
    path.unlink(missing_ok=True)
