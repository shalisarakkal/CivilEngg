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
    modelspace.add_line((0, 0), (100, 0), dxfattribs={"layer": "PROPERTY LINE"})
    modelspace.add_line((0, 0), (0, 50), dxfattribs={"layer": "BUILDING FOOTPRINT"})
    modelspace.add_line((10, 10), (20, 10), dxfattribs={"layer": "DRIVEWAY"})
    modelspace.add_line((30, 10), (30, 20), dxfattribs={"layer": "CURB CUT"})
    modelspace.add_line((40, 10), (40, 20), dxfattribs={"layer": "MISC"})
    drawing.saveas(path)


def test_dxf_layers_classify_entities_by_semantic_type(
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

        project = client.post("/projects", json={"name": "Semantic Classification"}).json()
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

        by_layer = {
            entity["source_reference"]["layer"]: entity["properties"].get("semantic_type")
            for entity in entities
        }
        assert by_layer["PROPERTY LINE"] == "parcel_boundary"
        assert by_layer["BUILDING FOOTPRINT"] == "building_footprint"
        assert by_layer["DRIVEWAY"] == "driveway_road"
        assert by_layer["CURB CUT"] == "curb_cut"
        assert by_layer["MISC"] is None
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_csv_type_and_zoning_columns_are_classified(
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
        project = client.post("/projects", json={"name": "Zoning Tags"}).json()
        content = b"x,y,type,zoning\n1000,5000,Parcel Corner,R-1\n"
        uploaded = client.post(
            f"/projects/{project['id']}/files",
            files={"file": ("corner.csv", content, "text/csv")},
        ).json()
        processed = client.post(f"/projects/{project['id']}/files/{uploaded['id']}/process").json()
        assert processed["status"] == "completed"
        revision = client.post(
            f"/projects/{project['id']}/site-model/revisions/from-extraction/{uploaded['id']}"
        ).json()
        entities = client.get(
            f"/projects/{project['id']}/site-model/revisions/{revision['id']}/entities"
        ).json()

        point = next(entity for entity in entities if entity["entity_type"] == "point")
        assert point["properties"]["semantic_type"] == "parcel_boundary"
        assert point["properties"]["zoning"] == "R-1"
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()
