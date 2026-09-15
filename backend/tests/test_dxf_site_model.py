from collections.abc import Generator
from pathlib import Path

import ezdxf
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from civil_engineering.database import Base, get_db
from civil_engineering.main import app


def _build_dxf(path: Path) -> None:
    drawing = ezdxf.new("R2010")  # type: ignore[attr-defined]
    modelspace = drawing.modelspace()
    modelspace.add_line((0, 0), (100, 0), dxfattribs={"layer": "PROPERTY"})
    modelspace.add_text(
        "FF=102.50", dxfattribs={"layer": "ELEVATIONS", "insert": (5, 1)}
    ).dxf.insert = (5, 1, 0)
    modelspace.add_text(
        "Unrelated note", dxfattribs={"layer": "NOTES", "insert": (500, 500)}
    ).dxf.insert = (500, 500, 0)
    drawing.saveas(path)


def test_nearby_label_is_linked_to_geometry_and_far_label_is_not(
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
    client = TestClient(app)
    try:
        dxf_path = tmp_path / "site.dxf"
        _build_dxf(dxf_path)

        project = client.post("/projects", json={"name": "DXF Label Linking"}).json()
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

        line = next(entity for entity in entities if entity["entity_type"] == "line")
        near_label = next(
            entity for entity in entities if entity["properties"].get("text") == "FF=102.50"
        )
        far_label = next(
            entity for entity in entities if entity["properties"].get("text") == "Unrelated note"
        )

        linked = near_label["properties"]["linked_geometry"]
        assert linked["entity_id"] == line["id"]
        assert linked["entity_type"] == "line"
        assert linked["distance"] == 1.0
        assert linked["source_reference"] == line["source_reference"]

        assert "linked_geometry" not in far_label["properties"]
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()
