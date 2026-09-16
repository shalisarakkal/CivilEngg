from collections.abc import Generator
from pathlib import Path

from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from civil_engineering.database import Base, get_db
from civil_engineering.main import app


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


def _upload_and_build_revision(client: TestClient, project_id: str, csv_content: bytes) -> str:
    uploaded = client.post(
        f"/projects/{project_id}/files",
        files={"file": ("points.csv", csv_content, "text/csv")},
    ).json()
    processed = client.post(f"/projects/{project_id}/files/{uploaded['id']}/process").json()
    assert processed["status"] == "completed"
    revision = client.post(
        f"/projects/{project_id}/site-model/revisions/from-extraction/{uploaded['id']}"
    ).json()
    return str(revision["id"])


def test_setback_distance_question_answers_from_two_point_entities(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    try:
        project = client.post("/projects", json={"name": "Setback Site"}).json()
        revision_id = _upload_and_build_revision(client, project["id"], b"x,y\n0,0\n3,4\n")

        question = client.post(
            f"/projects/{project['id']}/questions",
            json={"question": "What is the setback distance?", "revision_ids": [revision_id]},
        )
        assert question.status_code == 200
        answer = question.json()["answer"]
        assert answer["result"] == 5.0
        assert answer["confidence"] == 0.9
        assert len(answer["source_references"]) == 2
        assert all(
            reference["file_name"] == "points.csv" for reference in answer["source_references"]
        )
    finally:
        app.dependency_overrides.clear()
        from civil_engineering.config import get_settings

        get_settings.cache_clear()


def test_setback_distance_question_is_ambiguous_with_three_point_entities(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    try:
        project = client.post("/projects", json={"name": "Ambiguous Site"}).json()
        revision_id = _upload_and_build_revision(client, project["id"], b"x,y\n0,0\n3,4\n10,10\n")

        question = client.post(
            f"/projects/{project['id']}/questions",
            json={"question": "What is the setback distance?", "revision_ids": [revision_id]},
        )
        assert question.status_code == 200
        answer = question.json()["answer"]
        assert answer["confidence"] == 0.0
        assert "ambiguous" in answer["answer"].lower()
        assert len(answer["source_references"]) == 3
    finally:
        app.dependency_overrides.clear()
        from civil_engineering.config import get_settings

        get_settings.cache_clear()


def test_question_without_revision_refuses_to_invent_a_measurement(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    try:
        project = client.post("/projects", json={"name": "No Data Site"}).json()
        question = client.post(
            f"/projects/{project['id']}/questions",
            json={"question": "What is the setback distance?"},
        )
        assert question.status_code == 200
        answer = question.json()["answer"]
        assert answer["confidence"] == 0.0
        assert "Insufficient data" in answer["answer"]
        assert "result" not in answer
    finally:
        app.dependency_overrides.clear()
        from civil_engineering.config import get_settings

        get_settings.cache_clear()


def _upload_process_accept(
    client: TestClient, project_id: str, file_name: str, csv_content: bytes
) -> dict:
    uploaded = client.post(
        f"/projects/{project_id}/files",
        files={"file": (file_name, csv_content, "text/csv")},
    ).json()
    processed = client.post(f"/projects/{project_id}/files/{uploaded['id']}/process").json()
    assert processed["status"] == "completed"
    revision = client.post(
        f"/projects/{project_id}/site-model/revisions/from-extraction/{uploaded['id']}"
    ).json()
    return {"file_id": uploaded["id"], "revision_id": revision["id"]}


def test_project_boundary_default_aggregates_across_multiple_files(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    try:
        project = client.post("/projects", json={"name": "Multi-File Site"}).json()
        # Each file contributes exactly one point; alone, neither has enough
        # geometry to answer a distance question. Only aggregating both (the
        # project-boundary default) yields the two points needed for 3-4-5.
        _upload_process_accept(client, project["id"], "a.csv", b"x,y\n0,0\n")
        _upload_process_accept(client, project["id"], "b.csv", b"x,y\n3,4\n")

        question = client.post(
            f"/projects/{project['id']}/questions",
            json={"question": "What is the setback distance?"},
        )
        assert question.status_code == 200
        body = question.json()
        answer = body["answer"]
        assert answer["confidence"] == 0.9
        assert answer["result"] == 5.0
        assert len(body["revision_ids"]) == 2
    finally:
        app.dependency_overrides.clear()
        from civil_engineering.config import get_settings

        get_settings.cache_clear()


def test_replacing_a_file_excludes_the_superseded_revision_from_project_boundary(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    try:
        project = client.post("/projects", json={"name": "Versioned Site"}).json()
        original = _upload_process_accept(client, project["id"], "survey.csv", b"x,y\n0,0\n")

        replaced = client.post(
            f"/projects/{project['id']}/files/{original['file_id']}/replace",
            files={"file": ("survey.csv", b"x,y\n3,4\n", "text/csv")},
        )
        assert replaced.status_code == 201
        new_file = replaced.json()
        assert new_file["document_group_id"] == original["file_id"]
        processed = client.post(
            f"/projects/{project['id']}/files/{new_file['id']}/process"
        ).json()
        assert processed["status"] == "completed"
        new_revision = client.post(
            f"/projects/{project['id']}/site-model/revisions/from-extraction/{new_file['id']}"
        ).json()

        # If the superseded file's revision were still included, this would see
        # both points (the old at 0,0 and the new at 3,4) and answer 5.0 instead.
        question = client.post(
            f"/projects/{project['id']}/questions",
            json={"question": "What is the setback distance?"},
        )
        assert question.status_code == 200
        body = question.json()
        assert body["revision_ids"] == [new_revision["id"]]
        answer = body["answer"]
        assert answer["confidence"] == 0.0
        assert "No two mapped geometries" in " ".join(answer["limitations"])

        original_file = client.get(f"/projects/{project['id']}/files").json()
        replaced_entry = next(f for f in original_file if f["id"] == original["file_id"])
        assert replaced_entry["superseded_by_id"] == new_file["id"]

        second_replace_attempt = client.post(
            f"/projects/{project['id']}/files/{original['file_id']}/replace",
            files={"file": ("survey.csv", b"x,y\n1,1\n", "text/csv")},
        )
        assert second_replace_attempt.status_code == 409
    finally:
        app.dependency_overrides.clear()
        from civil_engineering.config import get_settings

        get_settings.cache_clear()
