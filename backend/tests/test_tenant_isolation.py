"""Tenant-scoped query isolation (PLAN.md Phase 16's query-scoping slice,
DECISIONS.md ADR-010). Every existing test elsewhere in this suite leaves
tenant_id unset (None) on every row, which is why none of them needed to
change for this slice -- these tests are the ones that actually exercise
more than one tenant."""

from collections.abc import Generator
from pathlib import Path

from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from civil_engineering.auth import (
    ROLE_ADMIN,
    ROLE_PLATFORM_ADMIN,
    ROLE_POWER_USER,
    hash_password,
)
from civil_engineering.config import get_settings
from civil_engineering.database import Base, get_db
from civil_engineering.main import app
from civil_engineering.models import Tenant, User


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


def _seed_tenant(sessions: sessionmaker[Session], *, name: str) -> str:
    database = sessions()
    try:
        tenant = Tenant(name=name)
        database.add(tenant)
        database.commit()
        database.refresh(tenant)
        return tenant.id
    finally:
        database.close()


def _seed_user(
    sessions: sessionmaker[Session],
    *,
    username: str,
    role: str,
    tenant_id: str | None = None,
    password: str = "secret123",
) -> str:
    database = sessions()
    try:
        # Login is by email now, not username (PLAN.md Phase 16) -- derived
        # from username here purely so every existing call site (already
        # unique usernames per test's own isolated database) keeps working
        # without also having to name an email everywhere.
        user = User(
            username=username,
            email=f"{username}@example.com",
            password_hash=hash_password(password),
            role=role,
            tenant_id=tenant_id,
        )
        database.add(user)
        database.commit()
        database.refresh(user)
        return user.id
    finally:
        database.close()


def test_project_visibility_and_access_are_scoped_to_tenant(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    client, sessions = _make_client(tmp_path, monkeypatch)
    try:
        tenant_a = _seed_tenant(sessions, name="Acme Engineering")
        tenant_b = _seed_tenant(sessions, name="Beta Engineering")
        _seed_user(sessions, username="admin_a", role=ROLE_ADMIN, tenant_id=tenant_a)
        _seed_user(sessions, username="owner_b", role=ROLE_POWER_USER, tenant_id=tenant_b)

        client.post("/auth/login", json={"email": "owner_b@example.com", "password": "secret123"})
        project_b = client.post("/projects", json={"name": "Beta's Confidential Site"}).json()
        assert project_b["tenant_id"] == tenant_b
        client.post("/auth/logout")

        client.post("/auth/login", json={"email": "admin_a@example.com", "password": "secret123"})
        # admin is now tenant-scoped: sees nothing from tenant B, even though
        # admin used to see every project in the whole install.
        assert client.get("/projects").json() == []
        assert client.get(f"/projects/{project_b['id']}").status_code == 404
        assert client.post(f"/projects/{project_b['id']}/archive").status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_platform_admin_crosses_tenant_boundaries(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    client, sessions = _make_client(tmp_path, monkeypatch)
    try:
        tenant_a = _seed_tenant(sessions, name="Acme Engineering")
        tenant_b = _seed_tenant(sessions, name="Beta Engineering")
        _seed_user(sessions, username="owner_a", role=ROLE_POWER_USER, tenant_id=tenant_a)
        _seed_user(sessions, username="owner_b", role=ROLE_POWER_USER, tenant_id=tenant_b)
        _seed_user(sessions, username="platform", role=ROLE_PLATFORM_ADMIN, tenant_id=None)

        client.post("/auth/login", json={"email": "owner_a@example.com", "password": "secret123"})
        project_a = client.post("/projects", json={"name": "Acme Site"}).json()
        client.post("/auth/logout")

        client.post("/auth/login", json={"email": "owner_b@example.com", "password": "secret123"})
        project_b = client.post("/projects", json={"name": "Beta Site"}).json()
        client.post("/auth/logout")

        client.post("/auth/login", json={"email": "platform@example.com", "password": "secret123"})
        visible_ids = {p["id"] for p in client.get("/projects").json()}
        assert {project_a["id"], project_b["id"]} <= visible_ids
        assert client.get(f"/projects/{project_a['id']}").status_code == 200
        assert client.get(f"/projects/{project_b['id']}").status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_client_visibility_and_access_are_scoped_to_tenant(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    client, sessions = _make_client(tmp_path, monkeypatch)
    try:
        tenant_a = _seed_tenant(sessions, name="Acme Engineering")
        tenant_b = _seed_tenant(sessions, name="Beta Engineering")
        _seed_user(sessions, username="admin_a", role=ROLE_ADMIN, tenant_id=tenant_a)
        _seed_user(sessions, username="admin_b", role=ROLE_ADMIN, tenant_id=tenant_b)

        client.post("/auth/login", json={"email": "admin_b@example.com", "password": "secret123"})
        client_b = client.post("/clients", json={"name": "Beta's City Client"}).json()
        assert client_b["tenant_id"] == tenant_b
        client.post("/auth/logout")

        client.post("/auth/login", json={"email": "admin_a@example.com", "password": "secret123"})
        assert client.get("/clients").json() == []
        assert client.get(f"/clients/{client_b['id']}").status_code == 404
        assert client.patch(f"/clients/{client_b['id']}", json={"name": "x"}).status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_admin_user_management_is_scoped_to_tenant(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    client, sessions = _make_client(tmp_path, monkeypatch)
    try:
        tenant_a = _seed_tenant(sessions, name="Acme Engineering")
        tenant_b = _seed_tenant(sessions, name="Beta Engineering")
        _seed_user(sessions, username="admin_a", role=ROLE_ADMIN, tenant_id=tenant_a)
        user_b_id = _seed_user(
            sessions, username="user_b", role=ROLE_POWER_USER, tenant_id=tenant_b
        )

        client.post("/auth/login", json={"email": "admin_a@example.com", "password": "secret123"})
        usernames = {u["username"] for u in client.get("/users").json()}
        assert usernames == {"admin_a"}
        assert client.get("/users/lookup?username=user_b").status_code == 404
        assert client.patch(f"/users/{user_b_id}", json={"disabled": True}).status_code == 404
        assert client.delete(f"/users/{user_b_id}").status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_new_user_is_assigned_the_creating_admins_tenant(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    client, sessions = _make_client(tmp_path, monkeypatch)
    try:
        tenant_a = _seed_tenant(sessions, name="Acme Engineering")
        _seed_user(sessions, username="admin_a", role=ROLE_ADMIN, tenant_id=tenant_a)

        client.post("/auth/login", json={"email": "admin_a@example.com", "password": "secret123"})
        created = client.post(
            "/users",
            json={
                "username": "new_hire",
                "email": "new_hire@example.com",
                "password": "secret123",
                "role": "user",
            },
        ).json()
        assert created["tenant_id"] == tenant_a
    finally:
        app.dependency_overrides.clear()


def test_cannot_add_a_cross_tenant_collaborator_or_reassign_to_a_cross_tenant_owner(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    client, sessions = _make_client(tmp_path, monkeypatch)
    try:
        tenant_a = _seed_tenant(sessions, name="Acme Engineering")
        tenant_b = _seed_tenant(sessions, name="Beta Engineering")
        _seed_user(sessions, username="owner_a", role=ROLE_POWER_USER, tenant_id=tenant_a)
        outsider_id = _seed_user(
            sessions, username="outsider", role=ROLE_POWER_USER, tenant_id=tenant_b
        )

        client.post("/auth/login", json={"email": "owner_a@example.com", "password": "secret123"})
        project_a = client.post("/projects", json={"name": "Acme Site"}).json()

        add_member = client.post(
            f"/projects/{project_a['id']}/members", json={"user_id": outsider_id}
        )
        assert add_member.status_code == 422

        reassign = client.patch(
            f"/projects/{project_a['id']}/owner", json={"owner_id": outsider_id}
        )
        assert reassign.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_platform_admin_provisions_a_project_in_an_explicit_tenant(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    client, sessions = _make_client(tmp_path, monkeypatch)
    try:
        tenant_a = _seed_tenant(sessions, name="Acme Engineering")
        owner_a_id = _seed_user(
            sessions, username="owner_a", role=ROLE_POWER_USER, tenant_id=tenant_a
        )
        _seed_user(sessions, username="platform", role=ROLE_PLATFORM_ADMIN, tenant_id=None)

        client.post("/auth/login", json={"email": "platform@example.com", "password": "secret123"})
        missing_tenant = client.post(
            "/projects", json={"name": "Acme Site", "owner_id": owner_a_id}
        )
        assert missing_tenant.status_code == 422

        created = client.post(
            "/projects",
            json={"name": "Acme Site", "owner_id": owner_a_id, "tenant_id": tenant_a},
        )
        assert created.status_code == 201
        assert created.json()["tenant_id"] == tenant_a
    finally:
        app.dependency_overrides.clear()


def test_last_active_admin_protection_no_longer_crosses_tenants(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    # Before query scoping, any two admins anywhere in the install satisfied
    # this check; now that admin means "this tenant", tenant B's admin no
    # longer covers for tenant A losing its only one.
    client, sessions = _make_client(tmp_path, monkeypatch)
    try:
        tenant_a = _seed_tenant(sessions, name="Acme Engineering")
        tenant_b = _seed_tenant(sessions, name="Beta Engineering")
        admin_a_id = _seed_user(sessions, username="admin_a", role=ROLE_ADMIN, tenant_id=tenant_a)
        _seed_user(sessions, username="admin_b", role=ROLE_ADMIN, tenant_id=tenant_b)

        client.post("/auth/login", json={"email": "admin_a@example.com", "password": "secret123"})
        response = client.patch(f"/users/{admin_a_id}", json={"disabled": True})
        assert response.status_code == 409
    finally:
        app.dependency_overrides.clear()


def test_platform_admin_provisions_a_new_tenant_end_to_end(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    # The full provisioning flow: platform_admin creates a Tenant, then an
    # admin account inside it via POST /users (tenant_id already supported
    # there from the query-scoping slice) -- no separate "create tenant +
    # first admin" endpoint needed since the two already compose.
    client, sessions = _make_client(tmp_path, monkeypatch)
    try:
        _seed_user(sessions, username="platform", role=ROLE_PLATFORM_ADMIN, tenant_id=None)

        client.post("/auth/login", json={"email": "platform@example.com", "password": "secret123"})
        tenant = client.post("/tenants", json={"name": "New Customer LLC"})
        assert tenant.status_code == 201
        tenant_id = tenant.json()["id"]

        assert {t["name"] for t in client.get("/tenants").json()} == {"New Customer LLC"}

        first_admin = client.post(
            "/users",
            json={
                "username": "new_customer_admin",
                "email": "new_customer_admin@example.com",
                "password": "secret123",
                "role": "admin",
                "tenant_id": tenant_id,
            },
        )
        assert first_admin.status_code == 201
        assert first_admin.json()["tenant_id"] == tenant_id
    finally:
        app.dependency_overrides.clear()


def test_only_platform_admin_can_manage_tenants(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    client, sessions = _make_client(tmp_path, monkeypatch)
    try:
        tenant_a = _seed_tenant(sessions, name="Acme Engineering")
        _seed_user(sessions, username="admin_a", role=ROLE_ADMIN, tenant_id=tenant_a)

        client.post("/auth/login", json={"email": "admin_a@example.com", "password": "secret123"})
        assert client.post("/tenants", json={"name": "Sneaky Co"}).status_code == 403
        assert client.get("/tenants").status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_two_tenants_can_share_a_username_but_not_an_email(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    # The actual problem this slice closes: username is unique per tenant,
    # not globally (PLAN.md Phase 16) -- two different customers can each
    # have their own "jsmith". Login uses email instead, which stays
    # globally unique, so a login attempt is never ambiguous about which
    # tenant's "jsmith" is meant.
    client, sessions = _make_client(tmp_path, monkeypatch)
    try:
        tenant_a = _seed_tenant(sessions, name="Acme Engineering")
        tenant_b = _seed_tenant(sessions, name="Beta Engineering")
        _seed_user(sessions, username="admin_a", role=ROLE_ADMIN, tenant_id=tenant_a)
        _seed_user(sessions, username="admin_b", role=ROLE_ADMIN, tenant_id=tenant_b)

        client.post("/auth/login", json={"email": "admin_a@example.com", "password": "secret123"})
        first = client.post(
            "/users",
            json={
                "username": "jsmith",
                "email": "jsmith@acme.example.com",
                "password": "secret123",
                "role": "user",
            },
        )
        assert first.status_code == 201
        client.post("/auth/logout")

        client.post("/auth/login", json={"email": "admin_b@example.com", "password": "secret123"})
        # Same username, different tenant, different email -- allowed.
        second = client.post(
            "/users",
            json={
                "username": "jsmith",
                "email": "jsmith@beta.example.com",
                "password": "secret123",
                "role": "user",
            },
        )
        assert second.status_code == 201

        # The SAME email, even in a different tenant, is still rejected.
        duplicate_email = client.post(
            "/users",
            json={
                "username": "someone_else",
                "email": "jsmith@acme.example.com",
                "password": "secret123",
                "role": "user",
            },
        )
        assert duplicate_email.status_code == 409

        # Logging in as tenant A's "jsmith" only ever resolves that one
        # account, unambiguously, via email.
        login = client.post(
            "/auth/login", json={"email": "jsmith@acme.example.com", "password": "secret123"}
        )
        assert login.status_code == 200
        assert login.json()["tenant_id"] == tenant_a
    finally:
        app.dependency_overrides.clear()
