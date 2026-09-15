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
            json={"question": "What is the setback distance?", "revision_id": revision_id},
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
            json={"question": "What is the setback distance?", "revision_id": revision_id},
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
