from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from civil_engineering import storage
from civil_engineering.database import Base, get_db
from civil_engineering.main import app
from civil_engineering.models import ProcessingJob, SourceFile


def _client(tmp_path: Path, monkeypatch: MonkeyPatch) -> TestClient:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db() -> Generator[Session, None, None]:
        database = sessions()
        try:
            yield database
        finally:
            database.close()

    monkeypatch.setenv("LOCAL_STORAGE_PATH", str(tmp_path))
    from civil_engineering.config import get_settings

    get_settings.cache_clear()
    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def _teardown() -> None:
    app.dependency_overrides.clear()
    from civil_engineering.config import get_settings

    get_settings.cache_clear()


def test_a_file_stuck_processing_after_a_crash_can_be_retried(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    try:
        project = client.post("/projects", json={"name": "Recovery Site"}).json()
        uploaded = client.post(
            f"/projects/{project['id']}/files",
            files={"file": ("survey.txt", b"elevation=100", "text/plain")},
        ).json()

        # Simulate a server crash that left the job and file stuck mid-processing
        # by reaching into the overridden session factory to mutate state directly.
        db_gen = app.dependency_overrides[get_db]()
        database = next(db_gen)
        source_file = database.get(SourceFile, uploaded["id"])
        assert source_file is not None
        stale_job = ProcessingJob(
            project_id=project["id"],
            source_file_id=uploaded["id"],
            status="processing",
            parser_name="text",
        )
        database.add(stale_job)
        source_file.status = "processing"
        database.commit()
        database.close()

        retried = client.post(f"/projects/{project['id']}/files/{uploaded['id']}/process")
        assert retried.status_code == 201
        assert retried.json()["status"] == "completed"

        refreshed_file = client.get(f"/projects/{project['id']}/files").json()[0]
        assert refreshed_file["status"] == "completed"
    finally:
        _teardown()


def test_malformed_pdf_fails_gracefully_without_crashing_the_server(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    try:
        project = client.post("/projects", json={"name": "Malformed Site"}).json()
        uploaded = client.post(
            f"/projects/{project['id']}/files",
            files={"file": ("plan.pdf", b"not a real pdf file", "application/pdf")},
        ).json()

        processed = client.post(f"/projects/{project['id']}/files/{uploaded['id']}/process")
        assert processed.status_code == 201
        assert processed.json()["status"] == "failed"
        assert processed.json()["error_message"]

        files = client.get(f"/projects/{project['id']}/files").json()
        assert files[0]["status"] == "failed"
        assert files[0]["error_message"]

        # The server must still be responsive after a parser failure.
        assert client.get("/health").status_code == 200
    finally:
        _teardown()


def test_oversized_file_upload_is_rejected_through_the_api(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    monkeypatch.setattr(storage, "MAX_FILE_SIZE", 10)
    try:
        project = client.post("/projects", json={"name": "Large File Site"}).json()

        uploaded = client.post(
            f"/projects/{project['id']}/files",
            files={"file": ("survey.csv", b"x" * 100, "text/csv")},
        )
        assert uploaded.status_code == 400
        assert client.get(f"/projects/{project['id']}/files").json() == []
    finally:
        _teardown()


def test_path_traversal_filename_is_rejected(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch)
    try:
        project = client.post("/projects", json={"name": "Traversal Site"}).json()

        uploaded = client.post(
            f"/projects/{project['id']}/files",
            files={"file": ("../../evil.txt", b"data", "text/plain")},
        )
        assert uploaded.status_code == 400
    finally:
        _teardown()


def _client_with_per_thread_connections(tmp_path: Path, monkeypatch: MonkeyPatch) -> TestClient:
    # A real per-request connection pool (unlike the shared single-connection
    # StaticPool used elsewhere) so concurrent requests behave the way they
    # would against Postgres, rather than corrupting a single shared cursor.
    engine = create_engine(f"sqlite:///{tmp_path / 'concurrency.db'}", connect_args={"timeout": 30})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db() -> Generator[Session, None, None]:
        database = sessions()
        try:
            yield database
        finally:
            database.close()

    monkeypatch.setenv("LOCAL_STORAGE_PATH", str(tmp_path))
    from civil_engineering.config import get_settings

    get_settings.cache_clear()
    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def test_concurrent_duplicate_uploads_only_accept_one(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    client = _client_with_per_thread_connections(tmp_path, monkeypatch)
    try:
        project = client.post("/projects", json={"name": "Concurrent Site"}).json()
        content = b"x,y\n0,0\n3,4\n"

        def upload(index: int) -> int:
            response = client.post(
                f"/projects/{project['id']}/files",
                files={"file": (f"points-{index}.csv", content, "text/csv")},
            )
            return response.status_code

        with ThreadPoolExecutor(max_workers=4) as executor:
            statuses = list(executor.map(upload, range(4)))

        assert statuses.count(201) == 1
        assert statuses.count(409) == 3

        files = client.get(f"/projects/{project['id']}/files").json()
        assert len(files) == 1
    finally:
        _teardown()


def test_concurrent_revision_accepts_get_unique_revision_numbers(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    client = _client_with_per_thread_connections(tmp_path, monkeypatch)
    try:
        project = client.post("/projects", json={"name": "Concurrent Accepts Site"}).json()
        file_ids = []
        for index in range(4):
            uploaded = client.post(
                f"/projects/{project['id']}/files",
                files={"file": (f"survey-{index}.txt", f"elevation={index}".encode(), "text/plain")},
            )
            assert uploaded.status_code == 201
            file_id = uploaded.json()["id"]
            processed = client.post(f"/projects/{project['id']}/files/{file_id}/process")
            assert processed.status_code == 201
            file_ids.append(file_id)

        def accept(file_id: str) -> dict:
            response = client.post(
                f"/projects/{project['id']}/site-model/revisions/from-extraction/{file_id}"
            )
            return {"status": response.status_code, "body": response.json()}

        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(accept, file_ids))

        assert all(result["status"] == 201 for result in results)
        revision_numbers = [result["body"]["revision_number"] for result in results]
        assert len(set(revision_numbers)) == len(revision_numbers)
    finally:
        _teardown()
