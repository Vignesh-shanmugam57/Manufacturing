"""CSV upload: validate the three source files and store them in PostgreSQL.

The dataset is recognised from the file's header (not its name), every row is validated, and rows are
inserted in batches. Uploading the same file twice is safe: existing ids are skipped (mode "append"),
or the table is emptied first (mode "replace").
"""
from __future__ import annotations

import csv
import datetime as dt
import io
from dataclasses import dataclass
from typing import Callable

from sqlalchemy import delete, func, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models import (AssetMachine, DataUpload, DowntimeEvent, EnergyReading, MachineReading, MaintenanceOrder,
                        NcrRecord, Plant, ProductionLine, ProductionRecord, QualityInspection, UtilityReading)
from app.services.analytics import invalidate_cache, memoized

MAX_PARAMS = 60000           # PostgreSQL allows 65535 bind parameters per statement
MAX_BATCH_ROWS = 2000


def _text(v: str) -> str | None:
    v = (v or "").strip()
    return v or None


def _float(v: str) -> float | None:
    v = (v or "").strip()
    return float(v) if v else None


def _bool(v: str) -> bool:
    return (v or "").strip().lower() in ("true", "1", "yes", "y", "t")


def _ts(v: str) -> dt.datetime:
    v = (v or "").strip()
    if not v:
        raise ValueError("empty timestamp")
    return dt.datetime.fromisoformat(v.replace("Z", "")).replace(tzinfo=None)


def _ts_opt(v: str) -> dt.datetime | None:
    return _ts(v) if (v or "").strip() else None


def _date_opt(v: str) -> dt.date | None:
    v = (v or "").strip()
    return dt.date.fromisoformat(v) if v else None


def _int_opt(v: str) -> int | None:
    v = (v or "").strip()
    return int(float(v)) if v else None


@dataclass(frozen=True)
class Dataset:
    key: str
    label: str
    file_name: str
    model: type
    id_column: str
    columns: dict[str, tuple[str, Callable]]   # csv column -> (model attribute, converter)
    time_attr: str | None      # None for register tables that have no time column
    purpose: str
    detect_key: str = ""       # a column only this file type has; defaults to the id column

    @property
    def required(self) -> set[str]:
        return set(self.columns)


DATASETS: dict[str, Dataset] = {
    "utility": Dataset(
        "utility", "Utility telemetry", "fact_utility_telemetry_hourly.csv", UtilityReading, "utility_reading_id",
        {"utility_reading_id": ("utility_reading_id", _text), "timestamp": ("ts", _ts),
         "plant_id": ("plant_id", _text), "utility_type": ("utility_type", _text), "zone": ("zone", _text),
         "flow_rate": ("flow_rate", _float), "pressure_bar": ("pressure_bar", _float),
         "temperature_c": ("temperature_c", _float), "consumption_unit": ("consumption_unit", _text),
         "equipment_id": ("equipment_id", _text), "operating_status": ("operating_status", _text),
         "alarm_code": ("alarm_code", _text)},
        "ts", "Hourly utility readings: compressed air, water, HVAC, nitrogen"),
    "machine": Dataset(
        "machine", "Machine telemetry", "fact_machine_telemetry_hourly.csv", MachineReading, "telemetry_id",
        {"telemetry_id": ("telemetry_id", _text), "timestamp": ("ts", _ts), "machine_id": ("machine_id", _text),
         "plant_id": ("plant_id", _text), "line_id": ("line_id", _text), "shift_id": ("shift_id", _text),
         "temperature_c": ("temperature_c", _float), "vibration_mm_s": ("vibration_mm_s", _float),
         "motor_current_a": ("motor_current_a", _float), "pressure_bar": ("pressure_bar", _float),
         "rpm": ("rpm", _float), "machine_state": ("machine_state", _text), "alarm_code": ("alarm_code", _text),
         "sensor_health": ("sensor_health", _text), "is_anomaly": ("is_anomaly", _bool)},
        "ts", "Machine operating conditions (state, temperature, vibration, current)"),
    "downtime": Dataset(
        "downtime", "Downtime events", "fact_downtime_event.csv", DowntimeEvent, "downtime_id",
        {"downtime_id": ("downtime_id", _text), "machine_id": ("machine_id", _text), "plant_id": ("plant_id", _text),
         "line_id": ("line_id", _text), "start_ts": ("start_ts", _ts), "duration_min": ("duration_min", _float),
         "reason_code": ("reason_code", _text), "impact_units": ("impact_units", _float),
         "maintenance_required": ("maintenance_required", _bool), "acknowledged_by": ("acknowledged_by", _text),
         "closure_status": ("closure_status", _text)},
        "start_ts", "Downtime events, correlated with utility usage"),
    "energy": Dataset(
        "energy", "Energy meters (hourly)", "fact_energy_meter_hourly.csv", EnergyReading, "meter_reading_id",
        {"meter_reading_id": ("meter_reading_id", _text), "timestamp": ("ts", _ts), "plant_id": ("plant_id", _text),
         "meter_id": ("meter_id", _text), "area": ("area", _text), "energy_source": ("energy_source", _text),
         "consumption_kwh": ("consumption_kwh", _float), "demand_kw": ("demand_kw", _float),
         "power_factor": ("power_factor", _float), "tariff_inr_per_kwh": ("tariff_inr_per_kwh", _float),
         "cost_inr": ("cost_inr", _float), "co2e_kg": ("co2e_kg", _float), "reading_quality": ("reading_quality", _text)},
        "ts", "Electricity per meter and area (compressor, chiller, HVAC, production), with cost and CO2"),
    "production": Dataset(
        "production", "Hourly production", "fact_hourly_production.csv", ProductionRecord, "event_id",
        {"event_id": ("event_id", _text), "event_ts": ("ts", _ts), "plant_id": ("plant_id", _text),
         "line_id": ("line_id", _text), "shift_id": ("shift_id", _text), "product_id": ("product_id", _text),
         "production_order_id": ("production_order_id", _text), "target_qty": ("target_qty", _float),
         "actual_qty": ("actual_qty", _float), "good_qty": ("good_qty", _float), "reject_qty": ("reject_qty", _float),
         "rework_qty": ("rework_qty", _float), "downtime_min": ("downtime_min", _float),
         "downtime_reason": ("downtime_reason", _text), "source_system": ("source_system", _text),
         "data_quality": ("data_quality", _text)},
        "ts", "Output, good and rejected units, and downtime per line and hour"),
    "maintenance": Dataset(
        "maintenance", "Maintenance work orders (CMMS)", "fact_maintenance_work_order.csv", MaintenanceOrder,
        "work_order_id",
        {"work_order_id": ("work_order_id", _text), "machine_id": ("machine_id", _text), "plant_id": ("plant_id", _text),
         "created_ts": ("created_ts", _ts), "maintenance_type": ("maintenance_type", _text),
         "failure_mode": ("failure_mode", _text), "priority": ("priority", _text),
         "planned_start": ("planned_start", _ts_opt), "actual_start": ("actual_start", _ts_opt),
         "downtime_avoided_estimate_min": ("downtime_avoided_estimate_min", _float), "status": ("status", _text),
         "technician_id": ("technician_id", _text)},
        "created_ts", "Preventive, predictive and corrective work orders on each machine"),
    "ncr": Dataset(
        "ncr", "Non-conformances and CAPA", "fact_ncr_capa.csv", NcrRecord, "ncr_id",
        {"ncr_id": ("ncr_id", _text), "inspection_id": ("inspection_id", _text), "opened_ts": ("opened_ts", _ts),
         "defect_code": ("defect_code", _text), "root_cause_category": ("root_cause_category", _text),
         "containment_action": ("containment_action", _text), "owner_id": ("owner_id", _text),
         "capa_due_date": ("capa_due_date", _date_opt), "capa_status": ("capa_status", _text),
         "effectiveness_check": ("effectiveness_check", _text)},
        "opened_ts", "Defects found, their root causes and the corrective actions still due"),
    "quality": Dataset(
        "quality", "Quality inspections", "fact_quality_inspection.csv", QualityInspection, "inspection_id",
        {"inspection_id": ("inspection_id", _text), "inspection_ts": ("inspection_ts", _ts),
         "plant_id": ("plant_id", _text), "line_id": ("line_id", _text), "station_id": ("station_id", _text),
         "product_id": ("product_id", _text), "serial_number": ("serial_number", _text),
         "production_order_id": ("production_order_id", _text), "inspection_stage": ("inspection_stage", _text),
         "defect_code": ("defect_code", _text), "result": ("result", _text), "severity": ("severity", _text),
         "measurement_value": ("measurement_value", _float), "spec_min": ("spec_min", _float),
         "spec_max": ("spec_max", _float), "inspector_id": ("inspector_id", _text),
         "disposition": ("disposition", _text), "spec_revision": ("spec_revision", _text),
         "source_system": ("source_system", _text)},
        "inspection_ts", "Pass and fail results against specification limits", detect_key="inspection_stage"),
    "assets": Dataset(
        "assets", "Asset register (machines)", "dim_machine.csv", AssetMachine, "machine_id",
        {"machine_id": ("machine_id", _text), "machine_name": ("machine_name", _text),
         "machine_type": ("machine_type", _text), "line_id": ("line_id", _text), "plant_id": ("plant_id", _text),
         "criticality": ("criticality", _text), "commissioned_date": ("commissioned_date", _date_opt),
         "planned_maintenance_interval_days": ("planned_maintenance_interval_days", _int_opt)},
        None, "Each machine, its type, line, criticality and planned maintenance interval",
        detect_key="machine_name"),
    "plants": Dataset(
        "plants", "Plants", "dim_plant.csv", Plant, "plant_id",
        {"plant_id": ("plant_id", _text), "plant_name": ("plant_name", _text), "country": ("country", _text),
         "state": ("state", _text), "timezone": ("timezone", _text), "calendar_id": ("calendar_id", _text),
         "currency": ("currency", _text)},
        None, "Plant names, location and currency", detect_key="plant_name"),
    "lines": Dataset(
        "lines", "Production lines", "dim_production_line.csv", ProductionLine, "line_id",
        {"line_id": ("line_id", _text), "plant_id": ("plant_id", _text), "line_type": ("line_type", _text),
         "nominal_capacity_per_hour": ("nominal_capacity_per_hour", _float), "takt_time_sec": ("takt_time_sec", _float),
         "area": ("area", _text)},
        None, "Line type, nominal capacity and takt time", detect_key="line_type"),
}


def detect_dataset(header: list[str]) -> str | None:
    cols = {h.strip() for h in header}
    for key, ds in DATASETS.items():
        if (ds.detect_key or ds.id_column) in cols:
            return key
    return None


def ingest_csv(s: Session, data: bytes, filename: str, dataset: str | None = None, mode: str = "append",
               user_id: str | None = None) -> dict:
    """Validate and store one CSV. Raises ValueError for an unusable file (the API returns it as HTTP 400)."""
    if mode not in ("append", "replace"):
        raise ValueError("mode must be 'append' or 'replace'.")
    if not data.strip():
        raise ValueError("The file is empty.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise ValueError("The file is not UTF-8 text; export it as a CSV (UTF-8).") from e
    reader = csv.DictReader(io.StringIO(text, newline=""))
    header = [h.strip() for h in (reader.fieldnames or [])]
    reader.fieldnames = header
    found = detect_dataset(header)
    if dataset in (None, "", "auto"):
        dataset = found
    if dataset not in DATASETS:
        raise ValueError("This CSV does not match any dataset the app knows. Its header must match one of the "
                         "files in docs/ (for example utility_reading_id, event_id or work_order_id).")
    ds = DATASETS[dataset]
    missing = sorted(ds.required - set(header))
    if missing:
        raise ValueError(f"{ds.label}: missing column(s) {', '.join(missing)}.")

    model = ds.model
    id_attr = ds.columns[ds.id_column][0]
    id_col = getattr(model, id_attr)
    time_col = getattr(model, ds.time_attr) if ds.time_attr else None

    if mode == "replace":
        s.execute(delete(model))

    rows_in_file = duplicates = invalid = inserted = 0
    errors: list[str] = []
    seen: set[str] = set()
    batch: list[dict] = []

    batch_rows = max(100, min(MAX_BATCH_ROWS, MAX_PARAMS // len(ds.columns)))
    dialect = s.get_bind().dialect.name

    def flush() -> int:
        """Insert the batch with ONE multi-row statement (one network round trip). In append mode rows whose id
        already exists are ignored by the database, so repeating an upload is safe."""
        nonlocal duplicates
        if not batch:
            return 0
        if mode == "append" and dialect in ("postgresql", "sqlite"):
            stmt = (pg_insert if dialect == "postgresql" else sqlite_insert)(model).values(batch)                 .on_conflict_do_nothing(index_elements=[id_attr])
            # RETURNING gives the exact number inserted (pg8000 reports rowcount -1 for multi-row inserts).
            n = len(s.execute(stmt.returning(id_col)).all())
        elif mode == "append":                       # other databases: look the ids up first
            ids = [r[id_attr] for r in batch]
            existing = set(s.scalars(select(id_col).where(id_col.in_(ids))))
            fresh = [r for r in batch if r[id_attr] not in existing]
            n = len(fresh)
            if fresh:
                s.execute(insert(model).values(fresh))
        else:
            s.execute(insert(model).values(batch))
            n = len(batch)
        duplicates += len(batch) - n
        batch.clear()
        return n

    for line_no, raw in enumerate(reader, start=2):
        rows_in_file += 1
        try:
            row = {attr: conv(raw.get(col, "")) for col, (attr, conv) in ds.columns.items()}
            if not row[id_attr]:
                raise ValueError(f"{ds.id_column} is empty")
            if row[id_attr] in seen:
                duplicates += 1
                continue
            seen.add(row[id_attr])
            batch.append(row)
        except (ValueError, TypeError) as e:
            invalid += 1
            if len(errors) < 5:
                errors.append(f"line {line_no}: {e}")
            continue
        if len(batch) >= batch_rows:
            inserted += flush()
    inserted += flush()

    if rows_in_file == 0:
        raise ValueError("The file has a header but no data rows.")
    if inserted == 0 and invalid == rows_in_file:
        s.rollback()
        raise ValueError(f"No valid rows. First problems: {'; '.join(errors)}")

    s.add(DataUpload(user_id=user_id, dataset=dataset, filename=(filename or ds.file_name)[:200], mode=mode,
                     rows_in_file=rows_in_file, rows_inserted=inserted, rows_skipped=duplicates + invalid))
    s.commit()
    invalidate_cache()
    total = s.scalar(select(func.count()).select_from(model))
    first, last = (s.execute(select(func.min(time_col), func.max(time_col))).one() if time_col is not None else (None, None))
    return {"dataset": dataset, "label": ds.label, "filename": filename, "mode": mode, "rows_in_file": rows_in_file,
            "inserted": inserted, "duplicates_skipped": duplicates, "invalid_skipped": invalid,
            "errors": errors, "total_rows": total, "first_ts": first, "last_ts": last}


@memoized   # about seven count/min/max queries; only an upload or a clear can change the answer
def dataset_status(s: Session) -> list[dict]:
    out = []
    for ds in DATASETS.values():
        if ds.time_attr:
            time_col = getattr(ds.model, ds.time_attr)
            count, first, last = s.execute(
                select(func.count(), func.min(time_col), func.max(time_col)).select_from(ds.model)).one()
        else:
            count, first, last = s.scalar(select(func.count()).select_from(ds.model)), None, None
        up = s.scalars(select(DataUpload).where(DataUpload.dataset == ds.key, DataUpload.mode != "clear")
                       .order_by(DataUpload.uploaded_at.desc(), DataUpload.id.desc()).limit(1)).first()
        out.append({"dataset": ds.key, "label": ds.label, "file_name": ds.file_name, "purpose": ds.purpose,
                    "rows": count, "first_ts": first, "last_ts": last,
                    "last_upload": None if up is None else {
                        "filename": up.filename, "uploaded_at": up.uploaded_at, "mode": up.mode,
                        "inserted": up.rows_inserted, "skipped": up.rows_skipped}})
    return out


def clear_dataset(s: Session, dataset: str) -> int:
    if dataset not in DATASETS:
        raise ValueError(f"Unknown dataset '{dataset}'. Use one of {list(DATASETS)}.")
    model = DATASETS[dataset].model
    n = s.scalar(select(func.count()).select_from(model)) or 0
    s.execute(delete(model))
    s.add(DataUpload(dataset=dataset, filename="(cleared)", mode="clear", rows_in_file=0, rows_inserted=0,
                     rows_skipped=n))
    s.commit()
    invalidate_cache()
    return n
