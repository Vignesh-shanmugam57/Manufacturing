"""The plant operations files: recognised by their headers, loaded with the same checks, summarised from the database.

Runs on the temporary test database (never Neon): conftest points DATABASE_URL at a temporary SQLite file.
"""
from app.db.session import SessionLocal
from app.services import alerts as al
from app.services import ingest, operations

ENERGY = """meter_reading_id,timestamp,date,plant_id,meter_id,area,energy_source,consumption_kwh,demand_kw,power_factor,tariff_inr_per_kwh,cost_inr,co2e_kg,reading_quality
EN-1,2026-10-30T10:00:00,2026-10-30,TP-1,MTR-C,COMPRESSOR,ELECTRICITY,100,50,0.9,8,800,60,VALID
EN-2,2026-10-30T11:00:00,2026-10-30,TP-1,MTR-S,SMT,ELECTRICITY,200,80,0.95,8,1600,120,VALID"""

PRODUCTION = """event_id,event_ts,event_date,year,month,week,day,hour,plant_id,line_id,shift_id,product_id,production_order_id,target_qty,actual_qty,good_qty,reject_qty,rework_qty,downtime_min,downtime_reason,operator_team,source_system,data_quality
PR-1,2026-10-30T10:00:00,2026-10-30,2026,10,44,5,10,TP-1,SMT-L1,C,PRD-A,PO-1,100,95,90,5,0,10,MICRO_STOP,T1,MES,VALID
PR-2,2026-10-30T11:00:00,2026-10-30,2026,10,44,5,11,TP-1,SMT-L1,C,PRD-A,PO-1,100,100,96,4,0,0,NONE,T1,MES,VALID"""

MAINTENANCE = """work_order_id,machine_id,plant_id,created_ts,maintenance_type,failure_mode,priority,planned_start,actual_start,downtime_avoided_estimate_min,status,technician_id
MWO-1,M-1,TP-1,2026-10-01T08:00:00,PREVENTIVE,N/A,P3,2026-10-02T08:00:00,2026-10-02T09:00:00,0,COMPLETED,E1
MWO-2,M-1,TP-1,2026-10-29T08:00:00,CORRECTIVE,BEARING_WEAR,P1,2026-10-29T10:00:00,,120,PLANNED,E2"""

MACHINES = """machine_id,machine_name,machine_type,line_id,plant_id,criticality,commissioned_date,planned_maintenance_interval_days
M-1,Test Machine,Pick and Place,SMT-L1,TP-1,A,2024-01-15,30
M-2,Second Machine,Reflow,SMT-L1,TP-1,B,2024-01-15,30"""

PLANTS = """plant_id,plant_name,country,state,timezone,calendar_id,currency
TP-1,Test Plant,India,Tamil Nadu,Asia/Kolkata,CAL-1,INR"""

LINES = """line_id,plant_id,line_type,nominal_capacity_per_hour,takt_time_sec,area
SMT-L1,TP-1,SMT,420,8.6,SMT"""

QUALITY = """inspection_id,inspection_ts,plant_id,line_id,station_id,product_id,serial_number,production_order_id,inspection_stage,defect_code,result,severity,measurement_value,spec_min,spec_max,inspector_id,disposition,spec_revision,source_system
QI-1,2026-10-30T10:00:00,TP-1,SMT-L1,ST-1,PRD-A,SN1,PO-1,OQC,NONE,PASS,NONE,98,95,100,E9,RELEASE,R1,QMS
QI-2,2026-10-30T11:00:00,TP-1,SMT-L1,ST-1,PRD-A,SN2,PO-1,OQC,D008,FAIL,MINOR,101,95,100,E9,REWORK,R1,QMS
QI-3,2026-10-30T10:30:00,TP-1,SMT-L1,ST-1,PRD-A,SN3,PO-1,OQC,NONE,PASS,NONE,97,95,100,E9,RELEASE,R1,QMS"""

NCR = """ncr_id,inspection_id,opened_ts,defect_code,root_cause_category,containment_action,owner_id,capa_due_date,capa_status,effectiveness_check
NCR-1,QI-2,2026-10-30T11:05:00,D008,ENVIRONMENT,100_PERCENT_SORT,E9,2026-10-01,IN_PROGRESS,PENDING"""

UTILITY = """utility_reading_id,timestamp,plant_id,utility_type,zone,flow_rate,pressure_bar,temperature_c,consumption_unit,equipment_id,operating_status,alarm_code
UT-1,2026-10-30T10:00:00,TP-1,COMPRESSED_AIR,ZA,80,6.5,20,m3,UTL-01,NORMAL,NONE
UT-2,2026-10-30T11:00:00,TP-1,COMPRESSED_AIR,ZA,81,5.9,20,m3,UTL-01,ALARM,PRESSURE_LOW"""


def test_each_plant_file_is_recognised_by_its_header():
    assert ingest.detect_dataset(ENERGY.splitlines()[0].split(",")) == "energy"
    assert ingest.detect_dataset(PRODUCTION.splitlines()[0].split(",")) == "production"
    assert ingest.detect_dataset(MAINTENANCE.splitlines()[0].split(",")) == "maintenance"
    assert ingest.detect_dataset(QUALITY.splitlines()[0].split(",")) == "quality"
    assert ingest.detect_dataset(NCR.splitlines()[0].split(",")) == "ncr"
    assert ingest.detect_dataset(MACHINES.splitlines()[0].split(",")) == "assets"
    assert ingest.detect_dataset(PLANTS.splitlines()[0].split(",")) == "plants"
    assert ingest.detect_dataset(LINES.splitlines()[0].split(",")) == "lines"
    # the older files still resolve to their own datasets
    assert ingest.detect_dataset(["utility_reading_id", "timestamp"]) == "utility"
    assert ingest.detect_dataset(["telemetry_id", "machine_id"]) == "machine"
    assert ingest.detect_dataset(["downtime_id", "machine_id"]) == "downtime"


def test_plant_summary_reads_what_was_loaded():
    with SessionLocal() as s:
        for name, text in [("energy.csv", ENERGY), ("production.csv", PRODUCTION), ("maintenance.csv", MAINTENANCE),
                           ("machines.csv", MACHINES), ("plants.csv", PLANTS), ("lines.csv", LINES),
                           ("quality.csv", QUALITY), ("ncr.csv", NCR), ("utility.csv", UTILITY)]:
            result = ingest.ingest_csv(s, text.encode(), name, "auto", "replace")
            assert result["invalid_skipped"] == 0, result["errors"]

        alert, _ = al.create_alert(s, utility_type="COMPRESSED_AIR", title="Test pressure alert", severity="MEDIUM",
                                   recommendation="Check the header", details="", plant_id="TP-1", zone="ZA",
                                   assigned_to="maintenance", category="test", source="test")
        al.assign_alert(s, alert.id, "Facilities team", by="test")
        out = operations.plant_summary(s, 30)

    assert out["empty"] is False
    assert out["as_of"].startswith("2026-10-30T11:00")

    energy = out["energy"]
    assert energy["total_kwh"] == 300
    assert energy["total_cost_inr"] == 2400
    assert energy["total_co2e_kg"] == 180
    compressor = next(x for x in energy["by_area"] if x["area"] == "COMPRESSOR")
    assert compressor["utility"] is True
    assert energy["kwh_per_good_unit"][0]["good_units"] == 186
    assert energy["kwh_per_good_unit"][0]["kwh_per_good_unit"] == 1.61

    line = out["production"]["lines"][0]
    assert line["line_type"] == "SMT"
    assert line["good"] == 186 and line["downtime_min"] == 10
    assert out["production"]["downtime_reasons"] == [{"reason": "MICRO_STOP", "minutes": 10, "events": 1}]

    maint = out["maintenance"]
    assert maint["orders_by_status"] == {"COMPLETED": 1, "PLANNED": 1}
    assert maint["top_failure_modes"] == [{"failure_mode": "BEARING_WEAR", "orders": 1}]
    # M-1 was serviced on 2 Oct and is due 30 days later, so it is not overdue; M-2 has never been serviced
    assert [m["machine_id"] for m in maint["overdue_service"]] == ["M-2"]

    quality = out["quality"]
    plant = quality["by_plant"][0]
    assert plant["inspections"] == 3 and plant["pass"] == 2
    assert plant["pass_rate_pct"] == 66.7
    assert quality["top_defects"] == [{"defect_code": "D008", "fails": 1}]
    assert quality["capa_overdue"] == 1          # due 1 Oct, still in progress on 30 Oct

    utilities = {u["utility"]: u for u in out["utilities"]["by_utility"]}
    assert utilities["COMPRESSED_AIR"]["availability_pct"] == 50.0     # one of two readings was normal
    assert utilities["COMPRESSED_AIR"]["alarms"] == {"PRESSURE_LOW": 1}

    assert out["workflow"]["open_by_owner"].get("Facilities team") == 1  # the alert went to the team we assigned

    # the day filter: the readings of 30 Oct are all on that day, and a day with no readings gives zero
    assert out["day_options"][0]["date"] == "2026-10-30"          # the latest day of data comes first
    assert len(out["day_options"]) == 7
    on_day = operations.plant_summary(s, 30, "2026-10-30")
    assert on_day["day"] == "2026-10-30"
    assert on_day["energy"]["total_kwh"] == 300
    assert on_day["production"]["lines"][0]["good"] == 186
    quiet = operations.plant_summary(s, 30, "2026-10-29")
    assert quiet["energy"]["total_kwh"] == 0
    assert quiet["production"]["lines"] == []
