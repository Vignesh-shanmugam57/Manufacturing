"""The finished analyses are cached until the data changes, and the signed-in user is remembered briefly."""
import time

from app.api import deps
from app.models import User
from app.services import analytics as an
from app.services import ingest
from tests.factory import make_csvs


def test_analysis_is_computed_once_and_returned_as_a_copy(session, monkeypatch):
    an.invalidate_cache()
    first = an.health_board(session)
    calls = []
    real = an.utility_rows
    monkeypatch.setattr(an, "utility_rows", lambda s: calls.append(1) or real(s))
    second = an.health_board(session)
    assert calls == []                       # served from the cache: no recomputation
    assert second == first
    second["open_alerts"] = 99               # routes add fields to the result; that must not leak into the cache
    assert "open_alerts" not in an.health_board(session)


def test_different_arguments_are_cached_separately(session):
    an.invalidate_cache()
    week = an.consumption_trends(session, period="week", periods=4)
    day = an.consumption_trends(session, period="day", periods=4)
    assert week != day
    assert an.consumption_trends(session, period="week", periods=4) == week


def test_upload_and_clear_drop_the_cached_results(session):
    an.invalidate_cache()
    before = an.health_board(session)
    status_before = ingest.dataset_status(session)
    ingest.clear_dataset(session, "downtime")
    try:
        assert ingest.dataset_status(session) != status_before
        assert next(d for d in ingest.dataset_status(session) if d["dataset"] == "downtime")["rows"] == 0
        assert an.health_board(session)["kpis"]["downtime_events_7d"] == 0
    finally:                                  # put the data back for the other tests
        ingest.ingest_csv(session, make_csvs()["downtime"], ingest.DATASETS["downtime"].file_name, mode="replace")
    after = an.health_board(session)
    assert after["kpis"] == before["kpis"]
    assert next(d for d in ingest.dataset_status(session) if d["dataset"] == "downtime")["rows"] > 0


def test_errors_are_not_cached(session):
    an.invalidate_cache()
    for _ in range(2):
        try:
            an.detect_abnormal_usage(session, 7, "not-a-utility")
        except ValueError:
            continue
        raise AssertionError("an unknown utility should raise every time")


def test_a_reading_written_straight_to_the_database_shows_up(session, monkeypatch):
    """A live feed inserts readings without any upload; the cache must notice it by itself."""
    import datetime as dt
    from sqlalchemy import delete

    from app.models import UtilityReading

    monkeypatch.setattr(an, "CACHE_TTL_S", 0.0)          # re-check on every call
    an.invalidate_cache()
    latest = an.as_of(session)
    board_before = an.health_board(session)
    assert board_before["as_of"] == latest

    new_ts = latest + dt.timedelta(hours=1)
    session.add(UtilityReading(utility_reading_id="LIVE-FEED-TEST", ts=new_ts, plant_id="P1", utility_type="HVAC",
                               zone="Z1", flow_rate=1.0, pressure_bar=1.0, temperature_c=20.0, consumption_unit="kWh",
                               equipment_id="E1", operating_status="NORMAL", alarm_code="NONE"))
    session.commit()
    try:
        assert an.as_of(session) == new_ts                      # no upload and no invalidate_cache() call
        assert an.health_board(session)["as_of"] == new_ts      # and the finished analysis was recomputed
    finally:
        session.execute(delete(UtilityReading).where(UtilityReading.utility_reading_id == "LIVE-FEED-TEST"))
        session.commit()
        an.invalidate_cache()
    assert an.as_of(session) == latest


def test_signed_in_user_is_remembered_then_expires(session, monkeypatch):
    user = User(email="cache.test@example.com", name="Cache Test")
    session.add(user)
    session.commit()
    deps.forget_users()
    assert deps.get_current_user(user.id).email == "cache.test@example.com"   # first call reads the database

    lookups = []
    real = deps.SessionLocal
    monkeypatch.setattr(deps, "SessionLocal", lambda: lookups.append(1) or real())
    assert deps.get_current_user(user.id).id == user.id
    assert lookups == []                                                      # second call: no database access

    monkeypatch.setattr(deps, "USER_TTL_S", 0.0)
    deps.remember_user(user)
    time.sleep(0.01)
    assert deps.get_current_user(user.id).id == user.id
    assert lookups == [1]                                                     # expired entry is looked up again
