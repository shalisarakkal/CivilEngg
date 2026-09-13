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
        assert entities.json()[0]["validation_status"] == "unmapped"
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
