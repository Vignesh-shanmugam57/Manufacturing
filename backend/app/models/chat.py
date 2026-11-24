"""Users, chat sessions and the user <-> agent messages (stored in Neon PostgreSQL)."""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, JSONType, utcnow_naive


def _uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str | None] = mapped_column(String(60))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow_naive)
    last_login_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow_naive)

    sessions: Mapped[list[ChatSession]] = relationship(back_populates="user", cascade="all, delete-orphan")


class ChatSession(Base):
    __tablename__ = "chat_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="New chat")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow_naive)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow_naive, index=True)

    user: Mapped[User] = relationship(back_populates="sessions")
    messages: Mapped[list[ChatMessage]] = relationship(back_populates="session", cascade="all, delete-orphan",
                                                       order_by="ChatMessage.id")


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20))            # user | assistant
    content: Mapped[str] = mapped_column(Text)
    steps: Mapped[list | None] = mapped_column(JSONType)     # agent tool trace (assistant messages)
    is_error: Mapped[bool] = mapped_column(Boolean, default=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    llm_calls: Mapped[int | None] = mapped_column(Integer)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow_naive)

    session: Mapped[ChatSession] = relationship(back_populates="messages")
