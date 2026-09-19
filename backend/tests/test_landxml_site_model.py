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

LANDXML_FIXTURE = b"""<?xml version="1.0"?>
<LandXML xmlns="http://www.landxml.org/schema/LandXML-1.2">
  <CgPoints>
    <CgPoint name="1">1000.00 5000.00 100.00</CgPoint>
    <CgPoint name="2">1000.00 5100.00 101.00</CgPoint>
  </CgPoints>
  <Alignments>
    <Alignment name="Centerline">
      <CoordGeom>
        <Line>
          <Start>1000.00 5000.00</Start>
          <End>1000.00 5100.00</End>
        </Line>
      </CoordGeom>
    </Alignment>
  </Alignments>
</LandXML>
"""


def test_landxml_fixture_produces_site_model_entities(
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
        project = client.post("/projects", json={"name": "LandXML Site"}).json()
        uploaded = client.post(
            f"/projects/{project['id']}/files",
            files={"file": ("corridor.xml", LANDXML_FIXTURE, "application/xml")},
        ).json()
        processed = client.post(f"/projects/{project['id']}/files/{uploaded['id']}/process").json()
        assert processed["status"] == "completed"
        revision = client.post(
            f"/projects/{project['id']}/site-model/revisions/from-extraction/{uploaded['id']}"
        ).json()
        entities = client.get(
            f"/projects/{project['id']}/site-model/revisions/{revision['id']}/entities"
        ).json()
        assert {entity["entity_type"] for entity in entities} == {"point", "line"}
        assert all(entity["validation_status"] == "valid" for entity in entities)
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()
