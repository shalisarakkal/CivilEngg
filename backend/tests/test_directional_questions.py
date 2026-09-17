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
    modelspace.add_line((-50, 100), (50, 100), dxfattribs={"layer": "PROPERTY LINE"})  # north
    modelspace.add_line((-50, -100), (50, -100), dxfattribs={"layer": "PROPERTY LINE"})  # south
    modelspace.add_line((50, -100), (50, 100), dxfattribs={"layer": "PROPERTY LINE"})  # east
    modelspace.add_line((-50, -100), (-50, 100), dxfattribs={"layer": "PROPERTY LINE"})  # west
    modelspace.add_point((0, 0), dxfattribs={"layer": "BUILDING FOOTPRINT"})
    drawing.saveas(path)


def test_directional_question_resolves_the_north_boundary_via_the_api(
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
        dxf_path = tmp_path / "parcel.dxf"
        _build_dxf(dxf_path)

        project = client.post("/projects", json={"name": "Directional Question Site"}).json()
        uploaded = client.post(
            f"/projects/{project['id']}/files",
            files={"file": ("parcel.dxf", dxf_path.read_bytes(), "application/dxf")},
        ).json()
        processed = client.post(f"/projects/{project['id']}/files/{uploaded['id']}/process").json()
        assert processed["status"] == "completed"
        revision = client.post(
            f"/projects/{project['id']}/site-model/revisions/from-extraction/{uploaded['id']}"
        ).json()

        directional = client.post(
            f"/projects/{project['id']}/questions",
            json={
                "question": "What is the distance to the north property line?",
                "revision_ids": [revision["id"]],
            },
        )
        assert directional.status_code == 200
        directional_payload = directional.json()
        assert directional_payload["intent"] == "directional_distance"
        directional_answer = directional_payload["answer"]
        assert directional_answer["result"] == 100.0
        assert directional_answer["confidence"] == 0.9

        # The same site model asked generically is ambiguous: five valid geometries
        # (four boundary lines and the building) give no way to pick which two to
        # compare, unlike the directional question which resolves a specific answer.
        generic = client.post(
            f"/projects/{project['id']}/questions",
            json={"question": "What is the setback distance?", "revision_ids": [revision["id"]]},
        )
        assert generic.status_code == 200
        generic_answer = generic.json()["answer"]
        assert "ambiguous" in generic_answer["answer"].lower()
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_directional_question_picks_the_correct_polygon_by_true_centroid(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    # Regression test: _entity_centroid averaged a closed ring's points without
    # dropping the repeated closing vertex, biasing a Polygon's centroid toward
    # whichever point happened to be listed first. Building A here is placed
    # south of Building B (true vertex-mean y: A=20, B=21), but A's first vertex
    # is its northernmost corner and B's is its southernmost, which used to bias
    # A's centroid up to 22 and B's down to 19 -- flipping which one "the north
    # building" resolved to.
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
        drawing = ezdxf.new("R2010")  # type: ignore[attr-defined]
        modelspace = drawing.modelspace()
        # Building A (entity 1): true centroid y=20, first vertex is its top
        # (northernmost) corner.
        modelspace.add_lwpolyline(
            [(0, 30), (10, 30), (10, 10), (0, 10)], close=True, dxfattribs={"layer": "BUILDING"}
        )
        # Building B (entity 2): true centroid y=21 (truly more north than A),
        # first vertex is its bottom (southernmost) corner.
        modelspace.add_lwpolyline(
            [(30, 11), (40, 11), (40, 31), (30, 31)], close=True, dxfattribs={"layer": "BUILDING"}
        )
        # A single other-typed entity so the resulting distance question isn't
        # ambiguous.
        modelspace.add_line((100, 0), (100, 50), dxfattribs={"layer": "PARCEL"})
        dxf_path = tmp_path / "buildings.dxf"
        drawing.saveas(dxf_path)

        project = client.post("/projects", json={"name": "Polygon Centroid Site"}).json()
        uploaded = client.post(
            f"/projects/{project['id']}/files",
            files={"file": ("buildings.dxf", dxf_path.read_bytes(), "application/dxf")},
        ).json()
        processed = client.post(f"/projects/{project['id']}/files/{uploaded['id']}/process").json()
        assert processed["status"] == "completed"
        revision = client.post(
            f"/projects/{project['id']}/site-model/revisions/from-extraction/{uploaded['id']}"
        ).json()
        entities = client.get(
            f"/projects/{project['id']}/site-model/revisions/{revision['id']}/entities"
        ).json()
        building_b = next(
            e
            for e in entities
            if e["entity_type"] == "lwpolyline" and e["source_reference"]["entity_id"] == "2"
        )

        directional = client.post(
            f"/projects/{project['id']}/questions",
            json={
                "question": "What is the distance to the north building?",
                "revision_ids": [revision["id"]],
            },
        )
        assert directional.status_code == 200
        answer = directional.json()["answer"]
        assert answer["confidence"] == 0.9
        # Entity B (true centroid y=21) must be the one picked as "north",
        # identifiable as the first of the two source references (the chosen
        # entity) in _answer_distance's response.
        assert answer["source_references"][0] == building_b["source_reference"]
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()
