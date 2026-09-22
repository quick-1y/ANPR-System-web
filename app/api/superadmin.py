"""The technical superadmin identity — defined entirely by the environment,
with no row in `users` (roadmap, `docs/roadmap/configuration-architecture.md`
section 14, "Будущий суперадмин не будет иметь строки в `users`").

Login is the fixed constant below; the password comes from
`config.env_settings.superadmin_password()` and is checked fresh on every
login, not seeded once into a table. `auth.py` (login) and `deps.py`
(`get_current_user`) special-case this identity *before* touching the
database — everywhere else in the codebase, a superadmin `current_user` dict
looks exactly like any other user dict and is handled the same way
(`role == "superadmin"` still means the same thing it always did).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

#: Fixed login of the technical superadmin — not configurable (roadmap 14).
SUPERADMIN_LOGIN = "superadmin"

#: Sentinel id used as the JWT `sub` and as this identity's synthetic `id`.
#: `users.id` is `BIGSERIAL`, which never issues 0, so this can never collide
#: with a real row.
SUPERADMIN_ID = 0

#: Process-start timestamp, reused for every synthetic user dict this process
#: builds. Nothing reads it specially for the superadmin; it exists only to
#: satisfy `UserOut`'s required `created_at`/`updated_at` fields.
_PROCESS_STARTED_AT = datetime.now(timezone.utc)


def is_superadmin_id(user_id: int) -> bool:
    """Whether *user_id* is the synthetic superadmin's sentinel id."""
    return user_id == SUPERADMIN_ID


def synthetic_superadmin() -> Dict[str, Any]:
    """The superadmin's user dict, shaped exactly like a DB row would be.

    No `password`/`password_changed_at` field: password verification happens
    once, at login, against the environment — nothing downstream reads a
    password hash off this dict.
    """
    return {
        "id": SUPERADMIN_ID,
        "login": SUPERADMIN_LOGIN,
        "role": "superadmin",
        "permissions": [],
        "is_active": True,
        "created_at": _PROCESS_STARTED_AT,
        "updated_at": _PROCESS_STARTED_AT,
        "password_changed_at": None,
    }


def audit_user_id(current_user: Dict[str, Any]) -> Optional[int]:
    """The id to attribute an `app_settings` write to.

    `app_settings.updated_by` has a foreign key to `users(id)`; the
    superadmin's sentinel id is never a row there, so writes attributed to it
    must store `NULL` instead — the column is already nullable
    (`ON DELETE SET NULL`) for exactly this "no specific user" case.
    """
    user_id = current_user.get("id")
    if user_id is None or is_superadmin_id(user_id):
        return None
    return user_id
