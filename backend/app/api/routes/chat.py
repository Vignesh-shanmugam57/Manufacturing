"""Talk to the agent. /chat returns when the answer is ready; /chat/stream sends progress as Server-Sent Events."""
import json
import queue
import threading

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.api.deps import CurrentUser, DbSession
from app.schemas.chat import ChatIn, ChatOut
from app.services import chat_service
from app.services.errors import NotFoundError

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatOut)
def chat(body: ChatIn, user: CurrentUser):
    return chat_service.send_message(user.id, body.session_id, body.message)


def _sse(event: dict) -> str:
    return f"event: {event['type']}\ndata: {json.dumps(event, default=str)}\n\n"


@router.post("/stream")
def chat_stream(body: ChatIn, user: CurrentUser, db: DbSession):
    """Events: session (user turn saved), thinking, tool_start, tool_end, final (assistant message), error."""
    if body.session_id:
        chat_service.get_owned_session(db, user.id, body.session_id)  # 404 before the stream starts
    db.close()

    events: queue.Queue = queue.Queue()

    def worker():
        try:
            out = chat_service.send_message(user.id, body.session_id, body.message, on_event=events.put)
            events.put({"type": "final", **out.model_dump(mode="json")})
        except NotFoundError as e:
            events.put({"type": "error", "detail": str(e)})
        except Exception as e:  # noqa: BLE001 - always end the stream with an error event
            events.put({"type": "error", "detail": f"Unexpected error: {e}"})
        finally:
            events.put(None)

    threading.Thread(target=worker, daemon=True, name="agent-run").start()

    def stream():
        yield ": connected\n\n"
        while (event := events.get()) is not None:
            yield _sse(event)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
