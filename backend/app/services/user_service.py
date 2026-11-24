from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User
from app.models.base import utcnow_naive


def login(db: Session, email: str, name: str, role: str | None = None) -> User:
    """Find the user by email or create them; updates name/role and last login."""
    now = utcnow_naive()
    user = db.scalar(select(User).where(User.email == email))
    if user:
        user.name = name
        user.role = role or user.role
        user.last_login_at = now
    else:
        user = User(email=email, name=name, role=role, created_at=now, last_login_at=now)
        db.add(user)
    db.commit()
    return user


def get_user(db: Session, user_id: str) -> User | None:
    return db.get(User, user_id)
