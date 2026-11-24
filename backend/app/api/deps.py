"""Shared API dependencies.

Users are identified by the X-User-Id header returned from POST /api/users/login. This is a lightweight
identity for an internal tool; put SSO / JWT in front of it before exposing the app beyond the plant network.
"""
import threading
import time
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.db.session import SessionLocal, get_db
from app.models import User

DbSession = Annotated[Session, Depends(get_db)]

# Every request used to look the user up in the database (a round trip to Neon, about a second). A signed-in
# user is remembered for a short time instead; login refreshes the entry.
USER_TTL_S = 120.0
_users: dict[str, tuple[float, User]] = {}
_users_lock = threading.Lock()


def remember_user(user: User) -> None:
    with _users_lock:
        _users[user.id] = (time.monotonic() + USER_TTL_S, user)


def forget_users() -> None:
    with _users_lock:
        _users.clear()


def get_current_user(x_user_id: Annotated[str | None, Header()] = None) -> User:
    if not x_user_id:
        raise HTTPException(401, "Sign in first (missing X-User-Id header).")
    with _users_lock:
        hit = _users.get(x_user_id)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    # Short-lived session: the returned user is detached, so no transaction is held during slow requests.
    with SessionLocal() as db:
        user = db.get(User, x_user_id)
    if user is None:
        raise HTTPException(401, "Unknown user. Please sign in again.")
    remember_user(user)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
