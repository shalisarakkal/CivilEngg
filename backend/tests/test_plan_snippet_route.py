from collections.abc import Generator
from pathlib import Path

import ezdxf
from auth_helpers import override_user_factory
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from civil_engineering.auth import get_current_user
from civil_engineering.database import Base, get_db
from civil_engineering.main import app


def _build_dxf(path: Path) -> None:
    drawing = ezdxf.new("R2010")  # type: ignore[attr-defined]
    modelspace = drawing.modelspace()
    modelspace.add_line((0, 0), (100, 0), dxfattribs={"layer": "PROPERTY"})
    modelspace.add_text("FF=102.50", dxfattribs={"layer": "ELEVATIONS", "insert": (5, 1)})
    drawing.saveas(path)


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
    app.dependency_overrides[get_current_user] = override_user_factory(sessions)
    return TestClient(app)


def test_plan_snippet_endpoint_returns_highlighted_svg_for_a_dxf_entity(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    try:
        dxf_path = tmp_path / "site.dxf"
        _build_dxf(dxf_path)

        project = client.post("/projects", json={"name": "Snippet Site"}).json()
        uploaded = client.post(
            f"/projects/{project['id']}/files",
            files={"file": ("site.dxf", dxf_path.read_bytes(), "application/dxf")},
        ).json()
        processed = client.post(f"/projects/{project['id']}/files/{uploaded['id']}/process").json()
        assert processed["status"] == "completed"
        revision = client.post(
            f"/projects/{project['id']}/site-model/revisions/from-extraction/{uploaded['id']}"
        ).json()
        entities = client.get(
            f"/projects/{project['id']}/site-model/revisions/{revision['id']}/entities"
        ).json()
        line_entity = next(entity for entity in entities if entity["entity_type"] == "line")

        response = client.get(
            f"/projects/{project['id']}/site-model/entities/{line_entity['id']}/snippet"
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/svg+xml"
        assert "#ff0000" in response.text
    finally:
        app.dependency_overrides.clear()
        from civil_engineering.config import get_settings

        get_settings.cache_clear()


def test_plan_snippet_endpoint_rejects_non_dxf_entities(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    try:
        project = client.post("/projects", json={"name": "Non-DXF Site"}).json()
        uploaded = client.post(
            f"/projects/{project['id']}/files",
            files={"file": ("points.csv", b"x,y\n0,0\n3,4\n", "text/csv")},
        ).json()
        processed = client.post(f"/projects/{project['id']}/files/{uploaded['id']}/process").json()
        assert processed["status"] == "completed"
        revision = client.post(
            f"/projects/{project['id']}/site-model/revisions/from-extraction/{uploaded['id']}"
        ).json()
        entities = client.get(
            f"/projects/{project['id']}/site-model/revisions/{revision['id']}/entities"
        ).json()

        response = client.get(
            f"/projects/{project['id']}/site-model/entities/{entities[0]['id']}/snippet"
        )
        assert response.status_code == 400
    finally:
        app.dependency_overrides.clear()
        from civil_engineering.config import get_settings

        get_settings.cache_clear()


def test_plan_snippet_endpoint_returns_404_for_unknown_entity(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    try:
        project = client.post("/projects", json={"name": "Empty Site"}).json()
        response = client.get(f"/projects/{project['id']}/site-model/entities/missing/snippet")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()
        from civil_engineering.config import get_settings

        get_settings.cache_clear()
