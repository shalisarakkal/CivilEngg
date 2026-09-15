from collections.abc import Generator
from pathlib import Path

from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from civil_engineering.database import Base, get_db
from civil_engineering.main import app


def test_bearing_distance_courses_produce_geometry_alongside_raw_coordinates(
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
        project = client.post("/projects", json={"name": "Parcel Boundary"}).json()
        content = (
            b"point_id,x,y,bearing,distance\n1,1000,5000,,\n2,,,N90.00E,100.00\n3,,,N45.00E,50.00\n"
        )
        uploaded = client.post(
            f"/projects/{project['id']}/files",
            files={"file": ("boundary.csv", content, "text/csv")},
        ).json()
        processed = client.post(f"/projects/{project['id']}/files/{uploaded['id']}/process").json()
        assert processed["status"] == "completed"
        revision = client.post(
            f"/projects/{project['id']}/site-model/revisions/from-extraction/{uploaded['id']}"
        ).json()
        entities = client.get(
            f"/projects/{project['id']}/site-model/revisions/{revision['id']}/entities"
        ).json()

        raw_point = next(entity for entity in entities if entity["entity_type"] == "point")
        assert raw_point["geometry"]["coordinates"] == [1000.0, 5000.0]
        assert raw_point["validation_status"] == "valid"

        courses = [entity for entity in entities if entity["entity_type"] == "cogo_line"]
        assert len(courses) == 2
        assert all(course["validation_status"] == "valid" for course in courses)
        first_course = next(
            course for course in courses if course["properties"]["bearing"] == "N90.00E"
        )
        assert first_course["geometry"]["coordinates"] == [[1000.0, 5000.0], [1100.0, 5000.0]]
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()
