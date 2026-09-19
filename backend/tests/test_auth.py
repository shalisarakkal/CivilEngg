"""Login/session mechanics and the role/ownership permission matrix (Phase 15)."""

from collections.abc import Generator
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from civil_engineering.auth import ROLE_ADMIN, ROLE_POWER_USER, ROLE_USER, hash_password
from civil_engineering.config import get_settings
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
    get_settings.cache_clear()
    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), sessions


def _seed_user(
    sessions: sessionmaker[Session],
    *,
    username: str,
    role: str,
    password: str = "password123",
    disabled: bool = False,
) -> str:
    database = sessions()
    try:
        user = User(
            username=username,
            password_hash=hash_password(password),
            role=role,
            disabled_at=datetime.now(timezone.utc) if disabled else None,
        )
        database.add(user)
        database.commit()
        database.refresh(user)
        return user.id
    finally:
        database.close()


def test_login_sets_cookie_and_me_returns_the_user(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    client, sessions = _make_client(tmp_path, monkeypatch)
    try:
        _seed_user(sessions, username="alice", role=ROLE_ADMIN, password="secret123")
        login = client.post("/auth/login", json={"username": "alice", "password": "secret123"})
        assert login.status_code == 200
        assert "session_id" in login.cookies
        me = client.get("/auth/me")
        assert me.status_code == 200
        assert me.json()["username"] == "alice"
        assert me.json()["role"] == ROLE_ADMIN
    finally:
        app.dependency_overrides.clear()


def test_login_wrong_password_is_rejected(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    client, sessions = _make_client(tmp_path, monkeypatch)
    try:
        _seed_user(sessions, username="bob", role=ROLE_USER, password="correct-password")
        login = client.post("/auth/login", json={"username": "bob", "password": "wrong"})
        assert login.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_disabled_user_cannot_login(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    client, sessions = _make_client(tmp_path, monkeypatch)
    try:
        _seed_user(sessions, username="carol", role=ROLE_USER, password="secret123", disabled=True)
        login = client.post("/auth/login", json={"username": "carol", "password": "secret123"})
        assert login.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_logout_then_me_is_unauthenticated(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    client, sessions = _make_client(tmp_path, monkeypatch)
    try:
        _seed_user(sessions, username="dave", role=ROLE_ADMIN, password="secret123")
        client.post("/auth/login", json={"username": "dave", "password": "secret123"})
        assert client.post("/auth/logout").status_code == 204
        assert client.get("/auth/me").status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_disabling_takes_effect_on_next_request_not_the_open_session(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    client, sessions = _make_client(tmp_path, monkeypatch)
    try:
        admin_id = _seed_user(sessions, username="admin", role=ROLE_ADMIN, password="secret123")
        target_id = _seed_user(sessions, username="target", role=ROLE_USER, password="secret123")
        client.post("/auth/login", json={"username": "admin", "password": "secret123"})
        assert client.get("/auth/me").status_code == 200

        # A second client holds the disabled user's own session.
        target_client, _ = (client.__class__(app), sessions)
        target_client.post("/auth/login", json={"username": "target", "password": "secret123"})
        assert target_client.get("/auth/me").status_code == 200

        disable = client.patch(f"/users/{target_id}", json={"disabled": True})
        assert disable.status_code == 200

        # Same still-open session, next request: now rejected.
        assert target_client.get("/auth/me").status_code == 401
        assert admin_id  # keep referenced
    finally:
        app.dependency_overrides.clear()


def test_cannot_disable_the_last_active_admin(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    client, sessions = _make_client(tmp_path, monkeypatch)
    try:
        admin_id = _seed_user(
            sessions, username="only-admin", role=ROLE_ADMIN, password="secret123"
        )
        client.post("/auth/login", json={"username": "only-admin", "password": "secret123"})
        response = client.patch(f"/users/{admin_id}", json={"disabled": True})
        assert response.status_code == 409
    finally:
        app.dependency_overrides.clear()


def test_power_user_creates_project_and_becomes_owner(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    client, sessions = _make_client(tmp_path, monkeypatch)
    try:
        power_user_id = _seed_user(
            sessions, username="pu", role=ROLE_POWER_USER, password="secret123"
        )
        client.post("/auth/login", json={"username": "pu", "password": "secret123"})
        created = client.post("/projects", json={"name": "Oak Street Site"})
        assert created.status_code == 201
        assert created.json()["owner_id"] == power_user_id
    finally:
        app.dependency_overrides.clear()


def test_plain_user_role_cannot_create_a_project(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    client, sessions = _make_client(tmp_path, monkeypatch)
    try:
        _seed_user(sessions, username="viewer", role=ROLE_USER, password="secret123")
        client.post("/auth/login", json={"username": "viewer", "password": "secret123"})
        response = client.post("/projects", json={"name": "Should Fail"})
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_non_member_gets_404_not_403_on_someone_elses_project(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    client, sessions = _make_client(tmp_path, monkeypatch)
    try:
        _seed_user(sessions, username="owner", role=ROLE_POWER_USER, password="secret123")
        _seed_user(sessions, username="outsider", role=ROLE_POWER_USER, password="secret123")

        client.post("/auth/login", json={"username": "owner", "password": "secret123"})
        project_id = client.post("/projects", json={"name": "Private Site"}).json()["id"]
        client.post("/auth/logout")

        client.post("/auth/login", json={"username": "outsider", "password": "secret123"})
        response = client.get(f"/projects/{project_id}")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_plain_user_member_can_upload_but_not_archive(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    client, sessions = _make_client(tmp_path, monkeypatch)
    try:
        _seed_user(sessions, username="owner2", role=ROLE_POWER_USER, password="secret123")
        member_id = _seed_user(sessions, username="member", role=ROLE_USER, password="secret123")

        client.post("/auth/login", json={"username": "owner2", "password": "secret123"})
        project_id = client.post("/projects", json={"name": "Shared Site"}).json()["id"]
        added = client.post(f"/projects/{project_id}/members", json={"user_id": member_id})
        assert added.status_code == 201
        client.post("/auth/logout")

        client.post("/auth/login", json={"username": "member", "password": "secret123"})
        assert client.get(f"/projects/{project_id}").status_code == 200
        upload = client.post(
            f"/projects/{project_id}/files",
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )
        assert upload.status_code == 201
        archive = client.post(f"/projects/{project_id}/archive")
        assert archive.status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_non_owner_power_user_member_cannot_archive_the_project(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    client, sessions = _make_client(tmp_path, monkeypatch)
    try:
        _seed_user(sessions, username="owner3", role=ROLE_POWER_USER, password="secret123")
        collaborator_id = _seed_user(
            sessions, username="collaborator", role=ROLE_POWER_USER, password="secret123"
        )

        client.post("/auth/login", json={"username": "owner3", "password": "secret123"})
        project_id = client.post("/projects", json={"name": "Co-owned Site"}).json()["id"]
        client.post(f"/projects/{project_id}/members", json={"user_id": collaborator_id})
        client.post("/auth/logout")

        client.post("/auth/login", json={"username": "collaborator", "password": "secret123"})
        # A collaborator has full working capabilities...
        assert client.get(f"/projects/{project_id}").status_code == 200
        # ...but project archive/delete stays owner-only.
        assert client.post(f"/projects/{project_id}/archive").status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_owner_reassignment_must_target_a_power_user(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    client, sessions = _make_client(tmp_path, monkeypatch)
    try:
        _seed_user(sessions, username="owner4", role=ROLE_POWER_USER, password="secret123")
        plain_user_id = _seed_user(sessions, username="plain", role=ROLE_USER, password="secret123")

        client.post("/auth/login", json={"username": "owner4", "password": "secret123"})
        project_id = client.post("/projects", json={"name": "Reassign Me"}).json()["id"]
        response = client.patch(f"/projects/{project_id}/owner", json={"owner_id": plain_user_id})
        assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_cannot_disable_a_user_who_still_owns_a_project(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    client, sessions = _make_client(tmp_path, monkeypatch)
    try:
        admin_id = _seed_user(sessions, username="admin2", role=ROLE_ADMIN, password="secret123")
        owner_id = _seed_user(
            sessions, username="owner5", role=ROLE_POWER_USER, password="secret123"
        )

        client.post("/auth/login", json={"username": "owner5", "password": "secret123"})
        client.post("/projects", json={"name": "Owned Site"})
        client.post("/auth/logout")

        client.post("/auth/login", json={"username": "admin2", "password": "secret123"})
        response = client.patch(f"/users/{owner_id}", json={"disabled": True})
        assert response.status_code == 422
        assert admin_id
    finally:
        app.dependency_overrides.clear()


def test_admin_can_access_any_project_without_membership(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    client, sessions = _make_client(tmp_path, monkeypatch)
    try:
        _seed_user(sessions, username="owner6", role=ROLE_POWER_USER, password="secret123")
        _seed_user(sessions, username="admin3", role=ROLE_ADMIN, password="secret123")

        client.post("/auth/login", json={"username": "owner6", "password": "secret123"})
        project_id = client.post("/projects", json={"name": "Admin Visible Site"}).json()["id"]
        client.post("/auth/logout")

        client.post("/auth/login", json={"username": "admin3", "password": "secret123"})
        assert client.get(f"/projects/{project_id}").status_code == 200
        assert client.post(f"/projects/{project_id}/archive").status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_non_admin_can_look_up_a_username_but_not_list_all_users(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    client, sessions = _make_client(tmp_path, monkeypatch)
    try:
        _seed_user(sessions, username="findme", role=ROLE_POWER_USER, password="secret123")
        _seed_user(sessions, username="searcher", role=ROLE_POWER_USER, password="secret123")

        client.post("/auth/login", json={"username": "searcher", "password": "secret123"})
        found = client.get("/users/lookup", params={"username": "findme"})
        assert found.status_code == 200
        assert found.json()["username"] == "findme"

        missing = client.get("/users/lookup", params={"username": "nobody-by-this-name"})
        assert missing.status_code == 404

        assert client.get("/users").status_code == 403
    finally:
        app.dependency_overrides.clear()
