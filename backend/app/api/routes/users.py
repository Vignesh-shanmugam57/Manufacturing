from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession, remember_user
from app.schemas.user import LoginIn, UserOut
from app.services import user_service

router = APIRouter(prefix="/users", tags=["users"])


@router.post("/login", response_model=UserOut)
def login(body: LoginIn, db: DbSession):
    """Sign in with email + name. Creates the user on first login."""
    user = user_service.login(db, body.email, body.name, body.role)
    remember_user(user)      # so the first requests after sign-in skip the user lookup
    return user


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser):
    return user
