"""GET /projects/{project_id}/collaborator-candidates: who "Manage
collaborators" can offer to add. Gated by require_project_owner (the
project's own owner, or an admin/platform_admin) -- the same access the
whole "Manage collaborators" panel already requires -- not admin-only like
GET /users, since a Power User project owner has no API access to that and
would otherwise be stuck typing an exact username instead of getting a
real dropdown. Cross-tenant scoping specifically is covered by this same
require_project_owner dependency already being exercised in
test_tenant_isolation.py for other project-scoped routes; not duplicated
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

from civil_engineering.auth import (
    ROLE_ADMIN,
    ROLE_POWER_USER,
    ROLE_USER,
    get_current_user,
    hash_password,
)
from civil_engineering.database import Base, get_db
from civil_engineering.main import app
from civil_engineering.models import User


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


def _seed_user(
    sessions: sessionmaker[Session], *, username: str, role: str, disabled: bool = False
) -> str:
    database = sessions()
    try:
        user = User(
            username=username,
            email=f"{username}@example.com",
            password_hash=hash_password("secret123"),
            role=role,
        )
        if disabled:
            from datetime import datetime, timezone

            user.disabled_at = datetime.now(timezone.utc)
        database.add(user)
        database.commit()
        database.refresh(user)
        return user.id
    finally:
        database.close()


def test_owner_sees_themselves_as_owner_and_eligible_candidates(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    client, sessions = _make_client(tmp_path, monkeypatch)
    jsmith_id = _seed_user(sessions, username="jsmith", role=ROLE_USER)
    pu_jane_id = _seed_user(sessions, username="pu_jane", role=ROLE_POWER_USER)

    project = client.post("/projects", json={"name": "Oak Street Site"}).json()
    response = client.get(f"/projects/{project['id']}/collaborator-candidates")
    assert response.status_code == 200
    body = response.json()
    assert body["owner"] == {"id": "test-user", "username": "test-user", "role": "power_user"}
    candidate_ids = {candidate["id"] for candidate in body["candidates"]}
    assert candidate_ids == {jsmith_id, pu_jane_id}


def test_excludes_disabled_accounts_and_non_user_power_user_roles(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    client, sessions = _make_client(tmp_path, monkeypatch)
    _seed_user(sessions, username="disabled_user", role=ROLE_USER, disabled=True)
    _seed_user(sessions, username="another_admin", role=ROLE_ADMIN)
    eligible_id = _seed_user(sessions, username="jsmith", role=ROLE_USER)

    project = client.post("/projects", json={"name": "Oak Street Site"}).json()
    body = client.get(f"/projects/{project['id']}/collaborator-candidates").json()
    candidate_ids = {candidate["id"] for candidate in body["candidates"]}
    assert candidate_ids == {eligible_id}


def test_excludes_existing_collaborators(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    client, sessions = _make_client(tmp_path, monkeypatch)
    jsmith_id = _seed_user(sessions, username="jsmith", role=ROLE_USER)

    project = client.post("/projects", json={"name": "Oak Street Site"}).json()
    added = client.post(f"/projects/{project['id']}/members", json={"user_id": jsmith_id})
    assert added.status_code == 201

    body = client.get(f"/projects/{project['id']}/collaborator-candidates").json()
    assert body["candidates"] == []


def test_a_project_member_who_is_not_owner_gets_403(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    client, sessions = _make_client(tmp_path, monkeypatch)
    collaborator_id = _seed_user(sessions, username="jsmith", role=ROLE_USER)

    project = client.post("/projects", json={"name": "Oak Street Site"}).json()
    client.post(f"/projects/{project['id']}/members", json={"user_id": collaborator_id})

    app.dependency_overrides[get_current_user] = override_user_factory(
        sessions, role=ROLE_USER, user_id=collaborator_id
    )
    try:
        response = client.get(f"/projects/{project['id']}/collaborator-candidates")
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_a_stranger_gets_404_not_403(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    client, sessions = _make_client(tmp_path, monkeypatch)
    project = client.post("/projects", json={"name": "Oak Street Site"}).json()

    app.dependency_overrides[get_current_user] = override_user_factory(
        sessions, role=ROLE_USER, user_id="stranger"
    )
    try:
        response = client.get(f"/projects/{project['id']}/collaborator-candidates")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_admin_can_see_candidates_for_a_project_they_dont_own(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    client, sessions = _make_client(tmp_path, monkeypatch)
    jsmith_id = _seed_user(sessions, username="jsmith", role=ROLE_USER)
    project = client.post("/projects", json={"name": "Oak Street Site"}).json()

    app.dependency_overrides[get_current_user] = override_user_factory(
        sessions, role=ROLE_ADMIN, user_id="the-admin"
    )
    try:
        response = client.get(f"/projects/{project['id']}/collaborator-candidates")
        assert response.status_code == 200
        body = response.json()
        assert body["owner"] == {"id": "test-user", "username": "test-user", "role": "power_user"}
        assert {candidate["id"] for candidate in body["candidates"]} == {jsmith_id}
    finally:
        app.dependency_overrides.clear()
