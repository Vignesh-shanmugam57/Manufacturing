"""Connections to the plant's data applications (databases, REST APIs, CSV links) and a log of every pull."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JSONType, utcnow_naive


class DataConnector(Base):
    __tablename__ = "data_connectors"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(30))                      # postgresql, mysql, sqlserver, rest_json, csv_url, demo_gateway
    config: Mapped[dict | None] = mapped_column(JSONType)              # everything that is not a secret
    secrets_enc: Mapped[str | None] = mapped_column(Text)              # passwords and tokens, encrypted; never sent to the browser
    target: Mapped[str] = mapped_column(String(40))                    # a dataset key (utility, energy ...) or "live_feed"
    mapping: Mapped[dict | None] = mapped_column(JSONType)             # {"columns": {app field: source column}, "constants": {...}}
    schedule_s: Mapped[int] = mapped_column(Integer, default=0)        # 0 = only when someone presses Pull now
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(10), default="NEW")     # NEW | OK | ERROR | RUNNING
    cursor: Mapped[dict | None] = mapped_column(JSONType)              # where the last pull stopped (incremental pulls)
    last_run_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    last_ok_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    last_rows_read: Mapped[int] = mapped_column(Integer, default=0)
    last_rows_stored: Mapped[int] = mapped_column(Integer, default=0)
    last_message: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow_naive)


class ConnectorRun(Base):
    __tablename__ = "connector_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    connector_id: Mapped[int] = mapped_column(ForeignKey("data_connectors.id", ondelete="CASCADE"), index=True)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow_naive)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    trigger: Mapped[str] = mapped_column(String(10), default="manual")  # manual | schedule | create
    rows_read: Mapped[int] = mapped_column(Integer, default=0)
    rows_stored: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str | None] = mapped_column(Text)
