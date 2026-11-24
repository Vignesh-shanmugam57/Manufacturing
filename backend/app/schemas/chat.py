import datetime as dt

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SessionCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class SessionUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    title: str
    created_at: dt.datetime
    updated_at: dt.datetime
    message_count: int = 0


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    role: str
    content: str
    steps: list[dict] | None = None
    is_error: bool = False
    duration_ms: int | None = None
    llm_calls: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    created_at: dt.datetime


class SessionDetail(SessionOut):
    messages: list[MessageOut] = []


class ChatIn(BaseModel):
    session_id: str | None = None
    message: str = Field(min_length=1, max_length=4000)

    @field_validator("message")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Message is empty.")
        return v


class ChatOut(BaseModel):
    session: SessionOut
    user_message: MessageOut
    assistant_message: MessageOut
