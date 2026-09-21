"""Phase 12's persisted, project-scoped activity/audit trail
(POST/GET /projects/{project_id}/activity-events). Complements the
frontend's own session-only activity log (cleared on reload) with a
durable copy readable by any project member after the fact. Cross-tenant
isolation specifically is covered in test_tenant_isolation.py alongside
every other project-scoped resource's isolation tests, not duplicated
here.
"""

from collections.abc import Generator
from pathlib import Path

from auth_helpers import override_user_factory
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from civil_engineering.auth import ROLE_USER, get_current_user
from civil_engineering.database import Base, get_db
from civil_engineering.main import app


def _make_client(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> tuple[TestClient, sessionmaker[Session]]:
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
    return TestClient(app), sessions


def test_activity_event_round_trips_with_details_and_recorded_user(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    client, _sessions = _make_client(tmp_path, monkeypatch)
    project = client.post("/projects", json={"name": "Oak Street Site"}).json()

    created = client.post(
        f"/projects/{project['id']}/activity-events",
        json={
            "text": "3 file(s): 2 accepted, 1 skipped.",
            "details": [
                {"name": "a.csv", "ok": True, "detail": ""},
                {"name": "b.csv", "ok": True, "detail": ""},
                {"name": "c.csv", "ok": False, "detail": "Revision already accepted"},
            ],
            "success_label": "Accepted",
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["project_id"] == project["id"]
    assert body["text"] == "3 file(s): 2 accepted, 1 skipped."
    assert body["success_label"] == "Accepted"
    assert len(body["details"]) == 3
    assert body["user_id"] == "test-user"  # override_user_factory's fixed identity
    assert body["username"] == "test-user"  # override_user_factory names the user after its id

    listed = client.get(f"/projects/{project['id']}/activity-events")
    assert listed.status_code == 200
    events = listed.json()
    assert len(events) == 1
    assert events[0]["id"] == body["id"]
    assert events[0]["username"] == "test-user"


def test_activity_events_default_to_no_details_and_a_successful_label(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    client, _sessions = _make_client(tmp_path, monkeypatch)
    project = client.post("/projects", json={"name": "Oak Street Site"}).json()

    created = client.post(
        f"/projects/{project['id']}/activity-events", json={"text": "Site summary generated."}
    )
    assert created.status_code == 201
    body = created.json()
    assert body["details"] is None
    assert body["success_label"] == "Successful"


def test_activity_events_are_listed_newest_first(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    client, _sessions = _make_client(tmp_path, monkeypatch)
    project = client.post("/projects", json={"name": "Oak Street Site"}).json()

    for text in ("First action.", "Second action.", "Third action."):
        response = client.post(f"/projects/{project['id']}/activity-events", json={"text": text})
        assert response.status_code == 201

    events = client.get(f"/projects/{project['id']}/activity-events").json()
    assert [event["text"] for event in events] == [
        "Third action.",
        "Second action.",
        "First action.",
    ]


def test_activity_events_limit_is_capped(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    client, _sessions = _make_client(tmp_path, monkeypatch)
    project = client.post("/projects", json={"name": "Oak Street Site"}).json()

    for index in range(5):
        client.post(f"/projects/{project['id']}/activity-events", json={"text": f"Action {index}."})

    assert len(client.get(f"/projects/{project['id']}/activity-events?limit=2").json()) == 2
    # A limit above the server-side cap (200) is clamped, not rejected or
    # honored verbatim -- an unbounded ?limit=100000 shouldn't be able to
    # force an unbounded query.
    assert len(client.get(f"/projects/{project['id']}/activity-events?limit=100000").json()) == 5


def test_a_nonmember_gets_404_not_the_events_of_a_project_they_cannot_see(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    # Both callers share the SAME database/project throughout -- the point
    # is that membership, not the project's mere existence, gates access,
    # matching every other project-scoped resource's require_project_member
    # behavior (404, not 403, so an unauthorized caller can't tell the
    # difference between "doesn't exist" and "exists, but not for you").
    client, sessions = _make_client(tmp_path, monkeypatch)
    project = client.post("/projects", json={"name": "Oak Street Site"}).json()
    client.post(
        f"/projects/{project['id']}/activity-events", json={"text": "Site summary generated."}
    )

    app.dependency_overrides[get_current_user] = override_user_factory(
        sessions, role=ROLE_USER, user_id="other-user"
    )
    try:
        assert client.get(f"/projects/{project['id']}/activity-events").status_code == 404
        assert (
            client.post(
                f"/projects/{project['id']}/activity-events",
                json={"text": "Should not be allowed."},
            ).status_code
            == 404
        )
    finally:
        app.dependency_overrides.clear()


def test_username_is_null_once_the_recording_user_is_gone(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    # username is denormalized from the related User at read time (routes.py's
    # _activity_event_response), not stored on the event itself -- once
    # user_id is gone (SET NULL on the user's own deletion), there's no
    # longer any account to look the name up from.
    from civil_engineering.models import ActivityEvent

    client, sessions = _make_client(tmp_path, monkeypatch)
    project = client.post("/projects", json={"name": "Oak Street Site"}).json()
    created = client.post(
        f"/projects/{project['id']}/activity-events", json={"text": "Site summary generated."}
    ).json()

    database = sessions()
    try:
        event = database.get(ActivityEvent, created["id"])
        assert event is not None
        event.user_id = None
        database.commit()
    finally:
        database.close()

    events = client.get(f"/projects/{project['id']}/activity-events").json()
    assert events[0]["user_id"] is None
    assert events[0]["username"] is None
