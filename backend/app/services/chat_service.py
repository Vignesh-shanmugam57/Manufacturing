"""Chat sessions and user <-> agent messages, persisted in PostgreSQL (Neon)."""
from __future__ import annotations

import logging

from langchain_core.language_models import BaseLLM
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agent.agent import EventCallback, run_agent
from app.agent.domo_llm import DomoAPIError
from app.db.session import SessionLocal
from app.models import ChatMessage, ChatSession
from app.models.base import utcnow_naive
from app.schemas.chat import ChatOut, MessageOut, SessionDetail, SessionOut
from app.services.errors import NotFoundError

log = logging.getLogger("utilities_agent.chat")
DEFAULT_TITLE = "New chat"


def _title(message: str) -> str:
    t = " ".join(message.split())
    return t if len(t) <= 60 else t[:57].rstrip() + "..."


def _count(db: Session, session_id: str) -> int:
    return db.scalar(select(func.count()).select_from(ChatMessage).where(ChatMessage.session_id == session_id)) or 0


def _session_out(db: Session, sess: ChatSession) -> SessionOut:
    return SessionOut.model_validate(sess).model_copy(update={"message_count": _count(db, sess.id)})


def get_owned_session(db: Session, user_id: str, session_id: str) -> ChatSession:
    sess = db.get(ChatSession, session_id)
    if sess is None or sess.user_id != user_id:
        raise NotFoundError("Chat session not found.")
    return sess


def list_sessions(db: Session, user_id: str) -> list[SessionOut]:
    counts = (select(ChatMessage.session_id, func.count().label("n"))
              .group_by(ChatMessage.session_id).subquery())
    rows = db.execute(
        select(ChatSession, func.coalesce(counts.c.n, 0))
        .outerjoin(counts, counts.c.session_id == ChatSession.id)
        .where(ChatSession.user_id == user_id)
        .order_by(ChatSession.updated_at.desc(), ChatSession.created_at.desc())).all()
    return [SessionOut.model_validate(s).model_copy(update={"message_count": n}) for s, n in rows]


def create_session(db: Session, user_id: str, title: str | None = None) -> ChatSession:
    now = utcnow_naive()
    sess = ChatSession(user_id=user_id, title=(title or DEFAULT_TITLE)[:200], created_at=now, updated_at=now)
    db.add(sess)
    db.commit()
    return sess


def session_detail(db: Session, user_id: str, session_id: str) -> SessionDetail:
    sess = get_owned_session(db, user_id, session_id)
    msgs = [MessageOut.model_validate(m) for m in sess.messages]
    return SessionDetail.model_validate(sess).model_copy(update={"messages": msgs, "message_count": len(msgs)})


def rename_session(db: Session, user_id: str, session_id: str, title: str) -> SessionOut:
    sess = get_owned_session(db, user_id, session_id)
    sess.title = title.strip()[:200]
    db.commit()
    return _session_out(db, sess)


def delete_session(db: Session, user_id: str, session_id: str) -> None:
    sess = get_owned_session(db, user_id, session_id)
    db.delete(sess)
    db.commit()


def send_message(user_id: str, session_id: str | None, message: str, on_event: EventCallback | None = None,
                 llm: BaseLLM | None = None) -> ChatOut:
    """Persist the user's message, run the agent, persist the agent's reply.

    The user turn is committed before the agent runs, so no database transaction stays open during the
    (slow) LLM calls - important behind Neon's pooled connections.
    """
    with SessionLocal() as db:
        sess = get_owned_session(db, user_id, session_id) if session_id else create_session(db, user_id)
        if sess.title == DEFAULT_TITLE:
            sess.title = _title(message)
        history = [{"role": m.role, "content": m.content} for m in sess.messages if not m.is_error]
        user_msg = ChatMessage(session_id=sess.id, role="user", content=message, created_at=utcnow_naive())
        db.add(user_msg)
        sess.updated_at = utcnow_naive()
        db.commit()
        sid = sess.id
        user_out = MessageOut.model_validate(user_msg)
        session_out = _session_out(db, sess)

    if on_event:
        on_event({"type": "session", "session": session_out.model_dump(mode="json"),
                  "user_message": user_out.model_dump(mode="json")})

    steps, usage, duration_ms, is_error = None, {}, None, False
    try:
        result = run_agent(message, history, llm=llm, on_event=on_event)
        content, steps, usage, duration_ms = result.answer, result.steps or None, result.usage, result.duration_ms
    except DomoAPIError as e:
        log.warning("Domo error: %s", e)
        content, is_error = f"The AI service is unavailable right now. {e}", True
    except Exception as e:  # noqa: BLE001 - keep the conversation consistent and report the failure
        log.exception("agent failed")
        content, is_error = f"The agent failed while answering: {e}", True

    with SessionLocal() as db:
        sess = db.get(ChatSession, sid)
        if sess is None:
            raise NotFoundError("Chat session was deleted while the agent was answering.")
        reply = ChatMessage(session_id=sid, role="assistant", content=content or "(no answer)", steps=steps,
                            is_error=is_error, duration_ms=duration_ms, llm_calls=usage.get("llm_calls"),
                            input_tokens=usage.get("input_tokens"), output_tokens=usage.get("output_tokens"),
                            created_at=utcnow_naive())
        db.add(reply)
        sess.updated_at = utcnow_naive()
        db.commit()
        return ChatOut(session=_session_out(db, sess), user_message=user_out,
                       assistant_message=MessageOut.model_validate(reply))
