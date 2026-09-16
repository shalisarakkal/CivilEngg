from collections.abc import Generator
from pathlib import Path

from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from civil_engineering.database import Base, get_db
from civil_engineering.main import app


def test_csv_rows_are_aggregated_or_mapped(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
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
        project = client.post("/projects", json={"name": "CSV Site"}).json()
        content = b"name,elevation\nA,100\nB,101\nC,102\n"
        uploaded = client.post(
            f"/projects/{project['id']}/files",
            files={"file": ("survey.csv", content, "text/csv")},
        ).json()
        processed = client.post(f"/projects/{project['id']}/files/{uploaded['id']}/process").json()
        assert processed["status"] == "completed"
        revision = client.post(
            f"/projects/{project['id']}/site-model/revisions/from-extraction/{uploaded['id']}"
        ).json()
        entities = client.get(
            f"/projects/{project['id']}/site-model/revisions/{revision['id']}/entities"
        ).json()
        assert len(entities) == 1
        assert entities[0]["entity_type"] == "table"
        assert entities[0]["properties"]["row_count"] == 3
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_csv_point_elevation_is_kept_as_the_z_coordinate(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    # Regression test: a CSV row's elevation column was being dropped when
    # building the row's point geometry (only x/y made it through), so an
    # elevation/slope question could never be answered from CSV point data
    # even though the source rows carried elevation values.
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
        project = client.post("/projects", json={"name": "Elevation Site"}).json()
        content = b"point_id,x,y,elevation\nA,0,0,100\nB,300,400,150\n"
        uploaded = client.post(
            f"/projects/{project['id']}/files",
            files={"file": ("points.csv", content, "text/csv")},
        ).json()
        client.post(f"/projects/{project['id']}/files/{uploaded['id']}/process")
        revision = client.post(
            f"/projects/{project['id']}/site-model/revisions/from-extraction/{uploaded['id']}"
        ).json()
        entities = client.get(
            f"/projects/{project['id']}/site-model/revisions/{revision['id']}/entities"
        ).json()
        points = [entity for entity in entities if entity["entity_type"] == "point"]
        assert len(points) == 2
        assert all(len(point["geometry"]["coordinates"]) == 3 for point in points)

        distance_answer = client.post(
            f"/projects/{project['id']}/questions",
            json={"question": "What is the distance between the two points?"},
        ).json()
        assert distance_answer["answer"]["result"] == 500.0

        slope_answer = client.post(
            f"/projects/{project['id']}/questions",
            json={"question": "What is the slope between the two points?"},
        ).json()
        assert slope_answer["answer"]["confidence"] > 0
        assert slope_answer["answer"]["result"] == 10.0
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()
