"""Shared helper for overriding get_current_user in tests written before auth existed.

These tests predate Phase 15 and don't exercise permissions themselves (see
test_auth.py/test_permissions.py for that) -- they just need a fixed identity
so existing business-logic assertions keep passing. A power_user is used
(not admin) because several of these tests call POST /projects with no
owner_id, which only auto-resolves for a power_user caller (an admin caller
must name an existing power_user as owner_id -- see create_project in
routes.py).

The user must actually be persisted in the test's own isolated database, not
just returned as an in-memory object: Project.owner_id is a real foreign key,
so creating a project as an unpersisted user trips a foreign-key violation
the moment a route tries to insert with that owner_id.
"""

from collections.abc import Callable

from sqlalchemy.orm import sessionmaker

from civil_engineering.auth import ROLE_POWER_USER
from civil_engineering.models import User


def override_user_factory(
    sessions: sessionmaker, role: str = ROLE_POWER_USER, user_id: str = "test-user"
) -> Callable[[], User]:
    def _get_current_user() -> User:
        database = sessions()
        try:
            user = database.get(User, user_id)
            if user is None:
                user = User(id=user_id, username=user_id, password_hash="unused", role=role)
                database.add(user)
                database.commit()
                database.refresh(user)
            return user
        finally:
            database.close()

    return _get_current_user
