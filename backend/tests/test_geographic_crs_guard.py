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
from civil_engineering.models import Project

SQUARE = {
    "type": "Polygon",
    "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]],
}


def test_geographic_crs_is_rejected_and_never_measured_on_a_plane(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    # A geographic (lat/lon degree) CRS breaks every planar formula in
    # calculations.py: Shapely would measure in degrees and the result would be
    # labelled feet or metres (see RISK_REGISTER.md). It is refused when a project
    # tries to adopt one, and refused again at measurement time for projects that
    # already carry one.
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
        rejected = client.post(
            "/projects", json={"name": "Lat Lon Site", "coordinate_reference_system": "EPSG:4326"}
        )
        assert rejected.status_code == 422
        assert "geographic" in rejected.json()["detail"]

        project = client.post(
            "/projects",
            json={"name": "State Plane Site", "coordinate_reference_system": "EPSG:2263"},
        ).json()
        assert (
            client.patch(
                f"/projects/{project['id']}",
                json={"coordinate_reference_system": "EPSG:4326"},
            ).status_code
            == 422
        )
        # A projected CRS, and clearing the CRS entirely, both stay allowed.
        assert (
            client.patch(
                f"/projects/{project['id']}",
                json={"coordinate_reference_system": None},
            ).status_code
            == 200
        )

        # Simulate a project stored before this validation existed.
        database = sessions()
        stored = database.get(Project, project["id"])
        assert stored is not None
        stored.coordinate_reference_system = "EPSG:4326"
        database.commit()
        database.close()

        area = client.post(
            f"/projects/{project['id']}/calculations",
            json={
                "calculation_type": "area",
                "inputs": {"geometry": SQUARE},
                "coordinate_unit": "ft",
                "unit": "ft",
            },
        )
        assert area.status_code == 400
        assert "geographic" in area.json()["detail"]

        # Slope is computed from supplied elevations and a supplied horizontal
        # distance, not from coordinate positions, so it is left alone.
        slope = client.post(
            f"/projects/{project['id']}/calculations",
            json={
                "calculation_type": "slope",
                "inputs": {
                    "start_elevation": 100.0,
                    "end_elevation": 104.0,
                    "horizontal_distance": 50.0,
                },
                "unit": "ft",
            },
        )
        assert slope.status_code == 201

        answer = client.post(
            f"/projects/{project['id']}/questions",
            json={"question": "What is the parcel area?"},
        ).json()
        assert answer["answer"]["answer"] == "Insufficient data to answer this question."
        assert any("geographic" in limit for limit in answer["answer"]["limitations"])

        summary = client.post(f"/projects/{project['id']}/summaries").json()
        assert any("geographic" in flag for flag in summary["content"]["attention_flags"])
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()
