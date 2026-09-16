from collections.abc import Generator
from pathlib import Path

from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from civil_engineering.database import Base, get_db
from civil_engineering.main import app


def test_project_file_workflow(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
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
    client = TestClient(app)

    try:
        created_project = client.post("/projects", json={"name": "Oak Street Site"})
        assert created_project.status_code == 201
        project_id = created_project.json()["id"]

        uploaded = client.post(
            f"/projects/{project_id}/files",
            files={"file": ("survey.txt", b"elevation=102.5", "text/plain")},
        )
        assert uploaded.status_code == 201
        file_data = uploaded.json()
        assert file_data["size_bytes"] == 15
        assert len(file_data["checksum"]) == 64

        duplicate = client.post(
            f"/projects/{project_id}/files",
            files={"file": ("copy.txt", b"elevation=102.5", "text/plain")},
        )
        assert duplicate.status_code == 409

        unsupported = client.post(
            f"/projects/{project_id}/files",
            files={"file": ("plan.exe", b"not supported", "application/octet-stream")},
        )
        assert unsupported.status_code == 400

        queued = client.post(f"/projects/{project_id}/files/{file_data['id']}/process")
        assert queued.status_code == 201
        assert queued.json()["status"] == "completed"
        assert (
            client.get(f"/projects/{project_id}/processing/{queued.json()['id']}").status_code
            == 200
        )
        extraction = client.get(f"/projects/{project_id}/files/{file_data['id']}/extraction")
        assert extraction.status_code == 200
        assert extraction.json()["parser_name"] == "text"

        site_model = client.post(
            f"/projects/{project_id}/site-model/revisions/from-extraction/{file_data['id']}"
        )
        assert site_model.status_code == 201
        revision_id = site_model.json()["id"]
        entities = client.get(f"/projects/{project_id}/site-model/revisions/{revision_id}/entities")
        assert entities.status_code == 200
        assert entities.json()[0]["entity_type"] == "text"
        assert entities.json()[0]["properties"]["line_count"] == 1
        repeated_revision = client.post(
            f"/projects/{project_id}/site-model/revisions/from-extraction/{file_data['id']}"
        )
        assert repeated_revision.status_code == 201
        assert repeated_revision.json()["id"] == revision_id

        calculation = client.post(
            f"/projects/{project_id}/calculations",
            json={
                "calculation_type": "slope",
                "inputs": {
                    "start_elevation": 100,
                    "end_elevation": 104,
                    "horizontal_distance": 100,
                },
                "unit": "ft",
            },
        )
        assert calculation.status_code == 201
        assert calculation.json()["result"] == 4
        assert calculation.json()["formula"]

        invalid_calculation = client.post(
            f"/projects/{project_id}/calculations",
            json={
                "calculation_type": "slope",
                "inputs": {
                    "start_elevation": 100,
                    "end_elevation": 104,
                    "horizontal_distance": 0,
                },
                "unit": "ft",
            },
        )
        assert invalid_calculation.status_code == 400

        summary = client.post(f"/projects/{project_id}/summaries")
        assert summary.status_code == 200
        assert "summary" in summary.json()["content"]
        question = client.post(
            f"/projects/{project_id}/questions",
            json={"question": "What is the setback distance?"},
        )
        assert question.status_code == 200
        assert question.json()["intent"] == "distance"
        assert question.json()["answer"]["confidence"] == 0.0

        elevation = client.post(
            f"/projects/{project_id}/calculations",
            json={
                "calculation_type": "elevation",
                "inputs": {"elevations": [100, 102, 104]},
                "unit": "ft",
            },
        )
        assert elevation.status_code == 201
        assert elevation.json()["details"]["minimum"] == 100

        deleted = client.delete(f"/projects/{project_id}/files/{file_data['id']}")
        assert deleted.status_code == 204
        assert client.get(f"/projects/{project_id}/files").json() == []
        assert client.get(f"/projects/{project_id}/site-model/revisions").json() == []
        assert (
            client.get(
                f"/projects/{project_id}/site-model/revisions/{revision_id}/entities"
            ).status_code
            == 404
        )
        archived = client.get("/admin/files/archived")
        assert archived.status_code == 200
        assert any(item["id"] == file_data["id"] for item in archived.json())
        restored = client.post(f"/admin/files/{file_data['id']}/restore")
        assert restored.status_code == 200
        assert client.get(f"/projects/{project_id}/files").json()[0]["id"] == file_data["id"]
        client.delete(f"/projects/{project_id}/files/{file_data['id']}")
        purged = client.delete(f"/admin/files/{file_data['id']}")
        assert purged.status_code == 204

        archived = client.post(f"/projects/{project_id}/archive")
        assert archived.status_code == 200
        assert client.get(f"/projects/{project_id}").status_code == 404
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_project_archive_restore_and_permanent_purge(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
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
    client = TestClient(app)

    try:
        project = client.post("/projects", json={"name": "Purge Site"}).json()
        project_id = project["id"]
        uploaded = client.post(
            f"/projects/{project_id}/files",
            files={"file": ("survey.txt", b"elevation=102.5", "text/plain")},
        ).json()
        storage_dir = tmp_path / project_id
        assert storage_dir.is_dir()

        # Archiving hides the project from normal routes but not from the admin list.
        assert client.post(f"/projects/{project_id}/archive").status_code == 200
        assert client.get(f"/projects/{project_id}").status_code == 404
        assert client.get("/projects").json() == []
        archived_list = client.get("/admin/projects/archived")
        assert archived_list.status_code == 200
        assert any(item["id"] == project_id for item in archived_list.json())

        # Restoring brings it back to normal routes.
        restored = client.post(f"/admin/projects/{project_id}/restore")
        assert restored.status_code == 200
        assert restored.json()["archived_at"] is None
        assert client.get(f"/projects/{project_id}").status_code == 200
        assert any(item["id"] == project_id for item in client.get("/projects").json())

        # A non-archived project can't be purged.
        assert client.delete(f"/admin/projects/{project_id}").status_code == 404

        # Archive again, then permanently purge: DB rows and storage directory both go.
        client.post(f"/projects/{project_id}/archive")
        purged = client.delete(f"/admin/projects/{project_id}")
        assert purged.status_code == 204
        assert client.get(f"/admin/projects/archived").json() == []
        assert not storage_dir.exists()

        # Purging twice (or restoring after purge) 404s: the project is gone.
        assert client.delete(f"/admin/projects/{project_id}").status_code == 404
        assert client.post(f"/admin/projects/{project_id}/restore").status_code == 404

        # The file row is gone too (cascaded from the project delete).
        from civil_engineering.models import SourceFile

        with sessions() as verify_session:
            assert verify_session.get(SourceFile, uploaded["id"]) is None
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()
