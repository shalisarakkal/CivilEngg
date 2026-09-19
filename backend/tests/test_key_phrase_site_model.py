from collections.abc import Generator
from pathlib import Path

from auth_helpers import override_user_factory
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from civil_engineering.auth import get_current_user
from civil_engineering.database import Base, get_db
from civil_engineering.main import app


def test_narrative_document_key_phrases_are_retrievable_as_site_model_entities(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
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
    app.dependency_overrides[get_current_user] = override_user_factory(sessions)
    client = TestClient(app)
    try:
        project = client.post("/projects", json={"name": "Narrative Notes"}).json()
        content = (
            b"The required setback is 25 feet from the property line.\n"
            b"Finished Floor Elevation shown on the plan.\n"
        )
        uploaded = client.post(
            f"/projects/{project['id']}/files",
            files={"file": ("notes.txt", content, "text/plain")},
        ).json()
        processed = client.post(f"/projects/{project['id']}/files/{uploaded['id']}/process").json()
        assert processed["status"] == "completed"
        revision = client.post(
            f"/projects/{project['id']}/site-model/revisions/from-extraction/{uploaded['id']}"
        ).json()
        entities = client.get(
            f"/projects/{project['id']}/site-model/revisions/{revision['id']}/entities"
        ).json()

        key_phrase_entities = [
            entity for entity in entities if entity["entity_type"] == "key_phrase"
        ]
        phrases_found = {entity["properties"]["phrase"] for entity in key_phrase_entities}
        assert phrases_found == {"setback", "property line", "finished floor elevation"}
        setback_entity = next(
            entity for entity in key_phrase_entities if entity["properties"]["phrase"] == "setback"
        )
        assert setback_entity["properties"]["context"] == (
            "The required setback is 25 feet from the property line."
        )
        assert setback_entity["source_reference"]["file_name"] == "notes.txt"
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()
