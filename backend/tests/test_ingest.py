import pytest
from sqlalchemy import func, select

from app.models import DataUpload, DowntimeEvent, UtilityReading
from app.services import ingest
from tests.factory import UTILITY_COLS, make_csvs

HEADER = ",".join(UTILITY_COLS)


def _restore(session):
    ingest.ingest_csv(session, make_csvs()["utility"], "fact_utility_telemetry_hourly.csv", mode="replace")


def test_detects_each_dataset_from_the_header():
    assert ingest.detect_dataset(["utility_reading_id", "timestamp"]) == "utility"
    assert ingest.detect_dataset(["telemetry_id", "timestamp"]) == "machine"
    assert ingest.detect_dataset(["downtime_id", "start_ts"]) == "downtime"
    assert ingest.detect_dataset(["a", "b"]) is None


def test_upload_is_idempotent_and_replace_resets(session):
    data = make_csvs()["downtime"]
    before = session.scalar(select(func.count()).select_from(DowntimeEvent))
    res = ingest.ingest_csv(session, data, "fact_downtime_event.csv", mode="append")
    assert res["inserted"] == 0 and res["duplicates_skipped"] == res["rows_in_file"] == before
    assert session.scalar(select(func.count()).select_from(DowntimeEvent)) == before
    res = ingest.ingest_csv(session, data, "fact_downtime_event.csv", mode="replace")
    assert res["inserted"] == before and res["total_rows"] == before
    assert session.scalar(select(func.count()).select_from(DataUpload)) >= 2


def test_new_rows_are_appended(session):
    extra = (HEADER + "\nUT-NEW-1,2026-10-01T00:00:00,P1,HVAC,SMT,50,6,22,m3,UTL-01,NORMAL,NONE\n"
             "UT-NEW-2,2026-10-01T01:00:00,P1,HVAC,SMT,51,6,22,m3,UTL-01,ALARM,PRESSURE_LOW\n").encode()
    res = ingest.ingest_csv(session, extra, "x.csv")
    assert res["dataset"] == "utility" and res["inserted"] == 2
    assert session.scalar(select(func.count()).select_from(UtilityReading).where(
        UtilityReading.utility_reading_id.like("UT-NEW-%"))) == 2
    _restore(session)


def test_invalid_rows_are_skipped_and_reported(session):
    csv = (HEADER + "\nUT-BAD-1,not-a-date,P1,HVAC,SMT,50,6,22,m3,UTL-01,NORMAL,NONE\n"
           "UT-BAD-2,2026-10-02T00:00:00,P1,HVAC,SMT,abc,6,22,m3,UTL-01,NORMAL,NONE\n"
           "UT-OK-3,2026-10-02T01:00:00,P1,HVAC,SMT,50,6,22,m3,UTL-01,NORMAL,NONE\n"
           "UT-OK-3,2026-10-02T01:00:00,P1,HVAC,SMT,50,6,22,m3,UTL-01,NORMAL,NONE\n").encode()
    res = ingest.ingest_csv(session, csv, "x.csv")
    assert (res["inserted"], res["invalid_skipped"], res["duplicates_skipped"]) == (1, 2, 1)
    assert len(res["errors"]) == 2 and res["errors"][0].startswith("line 2")
    _restore(session)


@pytest.mark.parametrize("data,msg", [
    (b"", "empty"),
    (b"a,b\n1,2\n", "does not match any dataset"),
    (b"utility_reading_id,timestamp\nUT-1,2026-01-01T00:00:00\n", "missing column"),
    ((HEADER + "\n").encode(), "no data rows"),
    ((HEADER + "\nUT-1,bad,P1,HVAC,SMT,1,1,1,m3,U,NORMAL,NONE\n").encode(), "No valid rows"),
    (b"\xff\xfe\x00bad", "UTF-8"),
])
def test_unusable_files_are_rejected(session, data, msg):
    with pytest.raises(ValueError, match=msg):
        ingest.ingest_csv(session, data, "x.csv")


def test_status_lists_every_dataset_the_app_knows(session):
    st = {d["dataset"]: d for d in ingest.dataset_status(session)}
    assert set(st) == set(ingest.DATASETS) and len(st) == 11
    assert st["utility"]["rows"] > 0 and st["utility"]["last_upload"]["filename"]
