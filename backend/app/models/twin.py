"""Digital-twin tables: equipment master, alerts with an audit trail, maintenance, downsampled history, settings."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JSONType, utcnow_naive


class TwinEquipment(Base):
    __tablename__ = "twin_equipment"
    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    utility: Mapped[str] = mapped_column(String(20))
    category: Mapped[str] = mapped_column(String(20))
    zone: Mapped[str] = mapped_column(String(40))
    criticality: Mapped[str] = mapped_column(String(10))
    last_maintenance: Mapped[dt.date | None] = mapped_column(Date)
    next_maintenance: Mapped[dt.date | None] = mapped_column(Date)


class TwinAlert(Base):
    __tablename__ = "twin_alerts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str | None] = mapped_column(String(14))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow_naive)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow_naive)
    utility: Mapped[str] = mapped_column(String(20))
    equipment_id: Mapped[str] = mapped_column(String(20), index=True)
    zone: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(10))          # INFO | WARNING | MAJOR | CRITICAL
    anomaly_type: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(200))
    actual: Mapped[str] = mapped_column(String(160), default="")
    expected: Mapped[str] = mapped_column(String(160), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    probable_cause: Mapped[str] = mapped_column(Text, default="")
    cause_certainty: Mapped[str] = mapped_column(String(10), default="PROBABLE")   # CONFIRMED | PROBABLE
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    recommendation: Mapped[str] = mapped_column(Text, default="")
    impact: Mapped[str] = mapped_column(Text, default="")
    consumers: Mapped[list | None] = mapped_column(JSONType)
    status: Mapped[str] = mapped_column(String(24), default="OPEN")
    assigned_to: Mapped[str | None] = mapped_column(String(60))
    source: Mapped[str] = mapped_column(String(12), default="SIMULATED")           # SIMULATED | LIVE
    acknowledged_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    closed_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    verification_note: Mapped[str | None] = mapped_column(Text)
    analysis: Mapped[dict | None] = mapped_column(JSONType)
    evidence: Mapped[list | None] = mapped_column(JSONType)


class TwinAlertEvent(Base):
    """Audit trail: every action on an alert, who did it and when."""
    __tablename__ = "twin_alert_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("twin_alerts.id", ondelete="CASCADE"), index=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow_naive)
    actor: Mapped[str] = mapped_column(String(120))
    action: Mapped[str] = mapped_column(String(40))
    detail: Mapped[str] = mapped_column(Text, default="")


class TwinMaintenance(Base):
    __tablename__ = "twin_maintenance"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    alert_id: Mapped[int | None] = mapped_column(ForeignKey("twin_alerts.id", ondelete="SET NULL"), index=True)
    equipment_id: Mapped[str] = mapped_column(String(20), index=True)
    maintenance_type: Mapped[str] = mapped_column(String(40))
    problem: Mapped[str] = mapped_column(String(240))
    recommendation: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[str] = mapped_column(String(10), default="MEDIUM")
    assigned_to: Mapped[str | None] = mapped_column(String(60))
    planned_date: Mapped[dt.date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(12), default="PENDING")   # PENDING|ASSIGNED|IN_PROGRESS|COMPLETED|VERIFIED
    notes: Mapped[str] = mapped_column(Text, default="")
    resolution: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(12), default="SIMULATED")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow_naive)
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    verified_at: Mapped[dt.datetime | None] = mapped_column(DateTime)


class TwinNotification(Base):
    __tablename__ = "twin_notifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow_naive)
    alert_id: Mapped[int | None] = mapped_column(ForeignKey("twin_alerts.id", ondelete="CASCADE"), index=True)
    recipient: Mapped[str] = mapped_column(String(40))           # a role: facilities, maintenance, plant_manager, safety
    channel: Mapped[str] = mapped_column(String(12), default="in-app")
    level: Mapped[str] = mapped_column(String(10), default="WARNING")
    message: Mapped[str] = mapped_column(String(300))
    escalated: Mapped[bool] = mapped_column(Boolean, default=False)


class TwinReading(Base):
    """Downsampled telemetry history (one row per sensor every few minutes; live values stay in memory)."""
    __tablename__ = "twin_readings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime)
    tag: Mapped[str] = mapped_column(String(60))
    value: Mapped[float] = mapped_column(Float)
    __table_args__ = (Index("ix_twin_readings_tag_ts", "tag", "ts"),)


class TwinSetting(Base):
    __tablename__ = "twin_settings"
    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[dict | None] = mapped_column(JSONType)


class TwinPerson(Base):
    """The plant team (mock roster for the proof of concept): who works which shift and which zones they cover."""
    __tablename__ = "twin_people"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(60), unique=True)
    role: Mapped[str] = mapped_column(String(60))                 # job title, e.g. Maintenance technician
    team: Mapped[str] = mapped_column(String(40), index=True)     # the team an alert is routed to
    shift: Mapped[str] = mapped_column(String(3))                 # A 06-14, B 14-22, C 22-06, ALL = on call 24 h
    phone_ext: Mapped[str | None] = mapped_column(String(12))
    zones: Mapped[list | None] = mapped_column(JSONType)          # zones covered; ["*"] = every zone
    active: Mapped[bool] = mapped_column(Boolean, default=True)
