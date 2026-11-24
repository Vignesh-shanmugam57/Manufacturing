"""Plant operations data from the docs/ folder: energy meters, production, maintenance (CMMS), quality, and the
asset register and plant structure.

  fact_energy_meter_hourly.csv     -> energy_readings      electricity per meter and area (compressor, chiller, HVAC ...)
  fact_hourly_production.csv       -> production_records   output, rejects and downtime per line and hour
  fact_maintenance_work_order.csv  -> maintenance_orders   CMMS work orders (preventive, predictive, corrective)
  fact_ncr_capa.csv                -> ncr_records          non-conformances and corrective actions
  fact_quality_inspection.csv      -> quality_inspections  inspection results against specification limits
  dim_machine.csv                  -> asset_machines       asset register: machine, type, line, criticality, interval
  dim_plant.csv                    -> plants               plant names, country, currency
  dim_production_line.csv          -> production_lines     line type, capacity and takt time
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import Date, DateTime, Float, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class EnergyReading(Base):
    __tablename__ = "energy_readings"
    meter_reading_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime, index=True)
    plant_id: Mapped[str] = mapped_column(String(20))
    meter_id: Mapped[str] = mapped_column(String(30))
    area: Mapped[str] = mapped_column(String(40))              # SMT, FAL, COMPRESSOR, CHILLER, HVAC ...
    energy_source: Mapped[str] = mapped_column(String(20))
    consumption_kwh: Mapped[float] = mapped_column(Float)
    demand_kw: Mapped[float | None] = mapped_column(Float)
    power_factor: Mapped[float | None] = mapped_column(Float)
    tariff_inr_per_kwh: Mapped[float | None] = mapped_column(Float)
    cost_inr: Mapped[float | None] = mapped_column(Float)
    co2e_kg: Mapped[float | None] = mapped_column(Float)
    reading_quality: Mapped[str | None] = mapped_column(String(15))
    __table_args__ = (Index("ix_energy_plant_ts", "plant_id", "ts"),)


class ProductionRecord(Base):
    __tablename__ = "production_records"
    event_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime, index=True)
    plant_id: Mapped[str] = mapped_column(String(20))
    line_id: Mapped[str] = mapped_column(String(20))
    shift_id: Mapped[str | None] = mapped_column(String(5))
    product_id: Mapped[str | None] = mapped_column(String(40))
    production_order_id: Mapped[str | None] = mapped_column(String(20))
    target_qty: Mapped[float | None] = mapped_column(Float)
    actual_qty: Mapped[float | None] = mapped_column(Float)
    good_qty: Mapped[float | None] = mapped_column(Float)
    reject_qty: Mapped[float | None] = mapped_column(Float)
    rework_qty: Mapped[float | None] = mapped_column(Float)
    downtime_min: Mapped[float | None] = mapped_column(Float)
    downtime_reason: Mapped[str | None] = mapped_column(String(40))
    source_system: Mapped[str | None] = mapped_column(String(20))
    data_quality: Mapped[str | None] = mapped_column(String(15))
    __table_args__ = (Index("ix_production_plant_ts", "plant_id", "ts"),)


class MaintenanceOrder(Base):
    __tablename__ = "maintenance_orders"
    work_order_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    machine_id: Mapped[str] = mapped_column(String(30), index=True)
    plant_id: Mapped[str] = mapped_column(String(20))
    created_ts: Mapped[dt.datetime] = mapped_column(DateTime, index=True)
    maintenance_type: Mapped[str] = mapped_column(String(20))       # PREVENTIVE | PREDICTIVE | CORRECTIVE
    failure_mode: Mapped[str | None] = mapped_column(String(40))
    priority: Mapped[str | None] = mapped_column(String(5))
    planned_start: Mapped[dt.datetime | None] = mapped_column(DateTime)
    actual_start: Mapped[dt.datetime | None] = mapped_column(DateTime)
    downtime_avoided_estimate_min: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(15))                 # PLANNED | IN_PROGRESS | COMPLETED
    technician_id: Mapped[str | None] = mapped_column(String(30))


class NcrRecord(Base):
    __tablename__ = "ncr_records"
    ncr_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    inspection_id: Mapped[str | None] = mapped_column(String(32))
    opened_ts: Mapped[dt.datetime] = mapped_column(DateTime, index=True)
    defect_code: Mapped[str | None] = mapped_column(String(10))
    root_cause_category: Mapped[str | None] = mapped_column(String(40))
    containment_action: Mapped[str | None] = mapped_column(String(60))
    owner_id: Mapped[str | None] = mapped_column(String(30))
    capa_due_date: Mapped[dt.date | None] = mapped_column(Date)
    capa_status: Mapped[str] = mapped_column(String(15))            # OPEN | IN_PROGRESS | CLOSED | VERIFIED
    effectiveness_check: Mapped[str | None] = mapped_column(String(20))


class QualityInspection(Base):
    __tablename__ = "quality_inspections"
    inspection_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    inspection_ts: Mapped[dt.datetime] = mapped_column(DateTime, index=True)
    plant_id: Mapped[str] = mapped_column(String(20))
    line_id: Mapped[str | None] = mapped_column(String(20))
    station_id: Mapped[str | None] = mapped_column(String(20))
    product_id: Mapped[str | None] = mapped_column(String(40))
    serial_number: Mapped[str | None] = mapped_column(String(30))
    production_order_id: Mapped[str | None] = mapped_column(String(20))
    inspection_stage: Mapped[str | None] = mapped_column(String(20))
    defect_code: Mapped[str | None] = mapped_column(String(10))
    result: Mapped[str] = mapped_column(String(10))                  # PASS | FAIL
    severity: Mapped[str | None] = mapped_column(String(10))
    measurement_value: Mapped[float | None] = mapped_column(Float)
    spec_min: Mapped[float | None] = mapped_column(Float)
    spec_max: Mapped[float | None] = mapped_column(Float)
    inspector_id: Mapped[str | None] = mapped_column(String(30))
    disposition: Mapped[str | None] = mapped_column(String(20))
    spec_revision: Mapped[str | None] = mapped_column(String(20))
    source_system: Mapped[str | None] = mapped_column(String(20))
    __table_args__ = (Index("ix_quality_plant_ts", "plant_id", "inspection_ts"),)


class AssetMachine(Base):
    __tablename__ = "asset_machines"
    machine_id: Mapped[str] = mapped_column(String(30), primary_key=True)
    machine_name: Mapped[str] = mapped_column(String(80))
    machine_type: Mapped[str | None] = mapped_column(String(40))
    line_id: Mapped[str | None] = mapped_column(String(20))
    plant_id: Mapped[str | None] = mapped_column(String(20))
    criticality: Mapped[str | None] = mapped_column(String(2))
    commissioned_date: Mapped[dt.date | None] = mapped_column(Date)
    planned_maintenance_interval_days: Mapped[int | None] = mapped_column(Integer)


class Plant(Base):
    __tablename__ = "plants"
    plant_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    plant_name: Mapped[str] = mapped_column(String(80))
    country: Mapped[str | None] = mapped_column(String(40))
    state: Mapped[str | None] = mapped_column(String(40))
    timezone: Mapped[str | None] = mapped_column(String(40))
    calendar_id: Mapped[str | None] = mapped_column(String(20))
    currency: Mapped[str | None] = mapped_column(String(5))


class ProductionLine(Base):
    __tablename__ = "production_lines"
    line_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    plant_id: Mapped[str] = mapped_column(String(20))
    line_type: Mapped[str] = mapped_column(String(40))
    nominal_capacity_per_hour: Mapped[float | None] = mapped_column(Float)
    takt_time_sec: Mapped[float | None] = mapped_column(Float)
    area: Mapped[str | None] = mapped_column(String(40))
