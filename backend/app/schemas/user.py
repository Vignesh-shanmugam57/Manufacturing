import datetime as dt
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class LoginIn(BaseModel):
    email: str = Field(max_length=254)
    name: str = Field(min_length=1, max_length=120)
    role: str | None = Field(default=None, max_length=60)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL.match(v):
            raise ValueError("Enter a valid email address.")
        return v

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("Name is required.")
        return v


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: str
    name: str
    role: str | None
    created_at: dt.datetime
    last_login_at: dt.datetime
