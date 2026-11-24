from fastapi import APIRouter, Response

from app.api.deps import CurrentUser, DbSession
from app.schemas.chat import SessionCreate, SessionDetail, SessionOut, SessionUpdate
from app.services import chat_service

router = APIRouter(prefix="/sessions", tags=["chat sessions"])


@router.get("", response_model=list[SessionOut])
def list_sessions(user: CurrentUser, db: DbSession):
    return chat_service.list_sessions(db, user.id)


@router.post("", response_model=SessionOut, status_code=201)
def create_session(body: SessionCreate, user: CurrentUser, db: DbSession):
    return chat_service.create_session(db, user.id, body.title)


@router.get("/{session_id}", response_model=SessionDetail)
def get_session(session_id: str, user: CurrentUser, db: DbSession):
    return chat_service.session_detail(db, user.id, session_id)


@router.patch("/{session_id}", response_model=SessionOut)
def rename_session(session_id: str, body: SessionUpdate, user: CurrentUser, db: DbSession):
    return chat_service.rename_session(db, user.id, session_id, body.title)


@router.delete("/{session_id}", status_code=204)
def delete_session(session_id: str, user: CurrentUser, db: DbSession):
    chat_service.delete_session(db, user.id, session_id)
    return Response(status_code=204)
