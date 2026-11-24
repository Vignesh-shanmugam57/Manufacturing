"""Plant data the agent analyses. The three fact tables are loaded from the CSV files the user uploads:

  fact_utility_telemetry_hourly.csv -> utility_readings   hourly utility readings (flow, pressure, temperature, alarms)
  fact_machine_telemetry_hourly.csv -> machine_readings   machine operating conditions
  fact_downtime_event.csv           -> downtime_events    downtime events, for correlation with utility usage

Agent outputs live in utility_alerts. data_uploads is the audit log of what was uploaded and by whom.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow_naive


class UtilityReading(Base):
    __tablename__ = "utility_readings"
    utility_reading_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime, index=True)
    plant_id: Mapped[str] = mapped_column(String(20))
    utility_type: Mapped[str] = mapped_column(String(30))     # COMPRESSED_AIR, CHILLED_WATER, HVAC, ...
    zone: Mapped[str] = mapped_column(String(40))
    flow_rate: Mapped[float | None] = mapped_column(Float)
    pressure_bar: Mapped[float | None] = mapped_column(Float)
    temperature_c: Mapped[float | None] = mapped_column(Float)
    consumption_unit: Mapped[str | None] = mapped_column(String(10))
    equipment_id: Mapped[str | None] = mapped_column(String(20))
    operating_status: Mapped[str | None] = mapped_column(String(15))   # NORMAL | ALARM
    alarm_code: Mapped[str | None] = mapped_column(String(30))         # NONE | PRESSURE_LOW ...
    __table_args__ = (Index("ix_utility_series_ts", "plant_id", "utility_type", "zone", "ts"),)


class MachineReading(Base):
    __tablename__ = "machine_readings"
    telemetry_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime, index=True)
    machine_id: Mapped[str] = mapped_column(String(30))
    plant_id: Mapped[str] = mapped_column(String(20))
    line_id: Mapped[str | None] = mapped_column(String(20))
    shift_id: Mapped[str | None] = mapped_column(String(5))
    temperature_c: Mapped[float | None] = mapped_column(Float)
    vibration_mm_s: Mapped[float | None] = mapped_column(Float)
    motor_current_a: Mapped[float | None] = mapped_column(Float)
    pressure_bar: Mapped[float | None] = mapped_column(Float)
    rpm: Mapped[float | None] = mapped_column(Float)
    machine_state: Mapped[str | None] = mapped_column(String(15))      # RUNNING | IDLE | SETUP | DOWN
    alarm_code: Mapped[str | None] = mapped_column(String(30))
    sensor_health: Mapped[str | None] = mapped_column(String(15))
    is_anomaly: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (Index("ix_machine_plant_ts", "plant_id", "ts"),)


class DowntimeEvent(Base):
    __tablename__ = "downtime_events"
    downtime_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    machine_id: Mapped[str] = mapped_column(String(30))
    plant_id: Mapped[str] = mapped_column(String(20))
    line_id: Mapped[str | None] = mapped_column(String(20))
    start_ts: Mapped[dt.datetime] = mapped_column(DateTime, index=True)
    duration_min: Mapped[float | None] = mapped_column(Float)
    reason_code: Mapped[str | None] = mapped_column(String(40))
    impact_units: Mapped[float | None] = mapped_column(Float)
    maintenance_required: Mapped[bool] = mapped_column(Boolean, default=False)
    acknowledged_by: Mapped[str | None] = mapped_column(String(30))
    closure_status: Mapped[str | None] = mapped_column(String(15))     # OPEN | CLOSED
    __table_args__ = (Index("ix_downtime_plant_ts", "plant_id", "start_ts"),)


class DataUpload(Base):
    __tablename__ = "data_uploads"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uploaded_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow_naive)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    dataset: Mapped[str] = mapped_column(String(20))          # utility | machine | downtime
    filename: Mapped[str] = mapped_column(String(200))
    mode: Mapped[str] = mapped_column(String(10))             # append | replace
    rows_in_file: Mapped[int] = mapped_column(Integer)
    rows_inserted: Mapped[int] = mapped_column(Integer)
    rows_skipped: Mapped[int] = mapped_column(Integer)        # duplicates already stored + invalid rows


class UtilityAlert(Base):
    __tablename__ = "utility_alerts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow_naive)
    utility_type: Mapped[str] = mapped_column(String(30))
    plant_id: Mapped[str | None] = mapped_column(String(20))
    zone: Mapped[str | None] = mapped_column(String(40))
    category: Mapped[str] = mapped_column(String(30))
    severity: Mapped[str] = mapped_column(String(10))
    title: Mapped[str] = mapped_column(String(200))
    details: Mapped[str] = mapped_column(Text, default="")
    recommendation: Mapped[str] = mapped_column(Text, default="")
    assigned_to: Mapped[str] = mapped_column(String(40), default="maintenance")
    source: Mapped[str] = mapped_column(String(20), default="agent")   # agent | scan | user
    status: Mapped[str] = mapped_column(String(15), default="OPEN")    # OPEN|ACKNOWLEDGED|RESOLVED|VERIFIED
    acknowledged_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    resolved_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    verified_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    status_note: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(String(120))
