"""Connectors: safety guards, encrypted secrets, the SQL, REST, CSV and demo adapters, and the API. No outside network."""
import csv
import datetime as dt
import io
import json
import sqlite3

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.connectors import demo, registry, safety, secrets as vault, service, web
from app.connectors.base import ConnectorError
from app.db.session import SessionLocal
from app.main import app
from app.models.connectors import DataConnector
from app.services import ingest
from app.services.analytics import invalidate_cache


# ------------------------------------------------------------------ helpers
@pytest.fixture
def clean():
    """Remove what these tests store, so the shared test data is exactly as it was."""
    yield
    with SessionLocal() as s:
        s.execute(text("DELETE FROM connector_runs"))
        s.execute(text("DELETE FROM data_connectors"))
        s.execute(text("DELETE FROM utility_readings WHERE utility_reading_id LIKE 'UT-DEMO-%' OR utility_reading_id LIKE 'T-CONN-%'"))
        s.commit()
    invalidate_cache()


def _utility_row(i: int, ts: dt.datetime) -> dict:
    return {"utility_reading_id": f"T-CONN-{i:04d}", "timestamp": ts.isoformat(), "plant_id": "IN-KA-01", "utility_type": "COMPRESSED_AIR", "zone": "T",
            "flow_rate": 80 + i, "pressure_bar": 6.1, "temperature_c": 20.5, "consumption_unit": "kWh", "equipment_id": "UTL-T", "operating_status": "NORMAL", "alarm_code": "NONE"}


def _mock_web(monkeypatch, handler):
    monkeypatch.setattr(web, "_client", lambda: httpx.Client(transport=httpx.MockTransport(handler)))


def _save(kind: str, config: dict, secrets: dict | None = None, target="utility", **extra):
    with SessionLocal() as s:
        c = service.create(s, {"kind": kind, "name": "t", "config": config, "secrets": secrets or {}, "target": target, **extra}, "tester")
        return c.id


@pytest.fixture
def api():
    with TestClient(app) as c:
        r = c.post("/api/users/login", json={"email": "conn.tester@example.com", "name": "Conn Tester", "role": "Utilities engineer"})
        c.headers.update({"X-User-Id": r.json()["id"]})
        yield c


# ------------------------------------------------------------------ safety
def test_sql_must_be_a_single_select():
    assert safety.assert_select("SELECT * FROM readings WHERE note = 'drop table x';") == "SELECT * FROM readings WHERE note = 'drop table x'"
    assert safety.assert_select("WITH a AS (SELECT 1) SELECT * FROM a")
    for bad in ["DELETE FROM readings", "SELECT 1; DROP TABLE readings", "UPDATE t SET a = 1", "SELECT * INTO copy FROM t",
                "WITH d AS (DELETE FROM t RETURNING *) SELECT * FROM d", "EXEC xp_cmdshell 'dir'", ""]:
        with pytest.raises(ValueError):
            safety.assert_select(bad)
    assert safety.assert_identifier("public.readings") == "public.readings"
    with pytest.raises(ValueError):
        safety.assert_identifier("readings; drop table x")


def test_web_addresses_are_checked():
    assert safety.check_url("http://127.0.0.1:8000/api/demo/utility.csv")
    for bad in ["http://169.254.169.254/latest/meta-data", "file:///etc/passwd", "ftp://host/x", "not a url", ""]:
        with pytest.raises(ValueError):
            safety.check_url(bad)


def test_passwords_are_encrypted_and_never_returned(clean):
    token = vault.encrypt({"password": "s3cret-pw"})
    assert "s3cret-pw" not in token and vault.decrypt(token) == {"password": "s3cret-pw"}
    cid = _save("postgresql", {"host": "h", "port": 5432, "database": "d", "username": "u"}, {"password": "s3cret-pw"})
    with SessionLocal() as s:
        c = s.get(DataConnector, cid)
        assert "s3cret-pw" not in (c.secrets_enc or "") and "password" not in (c.config or {})
        shown = json.dumps(service.connector_dict(c))
    assert "s3cret-pw" not in shown and '"secrets_set": ["password"]' in shown


# ------------------------------------------------------------------ mapping
def test_columns_are_matched_by_name():
    m = service.suggest_mapping("utility", ["Utility_Reading_ID", "TS", "plant_id", "x"])
    assert m["columns"]["utility_reading_id"] == "Utility_Reading_ID" and m["columns"]["timestamp"] == "TS" and "flow_rate" in m["missing"]
    assert service.suggest_mapping("live_feed", ["tag_name", "reading"])["columns"] == {"tag": "tag_name", "value": "reading"}


# ------------------------------------------------------------------ SQL, with a SQLite file standing in for the plant database
def test_sql_source_pulls_new_rows_only(tmp_path, monkeypatch, clean):
    db = tmp_path / "plant.db"
    con = sqlite3.connect(db)
    cols = list(demo.COLUMNS)
    con.execute(f"CREATE TABLE readings ({', '.join(cols)})")
    base = dt.datetime(2026, 11, 1)
    def add(a, b):
        for i in range(a, b):
            r = _utility_row(i, base + dt.timedelta(hours=i))
            con.execute(f"INSERT INTO readings VALUES ({','.join('?' * len(cols))})", [r[c] for c in cols])
        con.commit()
    add(0, 5)
    monkeypatch.setitem(registry.KINDS, "sqlite", dict(label="SQLite", category="Databases", icon="database", blurb="", adapter=registry.SQLITE_TEST,
                                                       fields=[registry.F("database", "File")]))
    src = {"mode": "table", "table": "readings", "cursor_column": "timestamp"}
    t = service.test_connection("sqlite", {"database": str(db)}, {}, src)
    assert t["ok"] and "readings" in t["tables"] and len(t["sample"]) == 5 and "timestamp" in t["columns"]

    cid = _save("sqlite", {"database": str(db), "source": src}, columns=cols)
    first = service.run(cid)
    assert first["ok"] and first["rows_read"] == 5 and first["rows_stored"] == 5
    again = service.run(cid)
    assert again["ok"] and again["rows_read"] == 0                           # the cursor remembers where it stopped
    add(5, 8)
    third = service.run(cid)
    assert third["rows_read"] == 3 and third["rows_stored"] == 3
    with SessionLocal() as s:
        assert s.execute(text("SELECT COUNT(*) FROM utility_readings WHERE utility_reading_id LIKE 'T-CONN-%'")).scalar() == 8
        assert s.get(DataConnector, cid).status == "OK"


def test_a_bad_query_is_refused_not_run(tmp_path, monkeypatch):
    monkeypatch.setitem(registry.KINDS, "sqlite", dict(label="SQLite", category="Databases", icon="database", blurb="", adapter=registry.SQLITE_TEST,
                                                       fields=[registry.F("database", "File")]))
    t = service.test_connection("sqlite", {"database": str(tmp_path / "x.db")}, {}, {"mode": "query", "query": "DELETE FROM readings"})
    assert not t["ok"] and "SELECT" in t["message"]


# ------------------------------------------------------------------ REST and CSV, with a mocked web server
def test_rest_json_finds_the_rows_and_sends_the_sign_in(monkeypatch, clean):
    seen = {}
    rows = [_utility_row(i, dt.datetime(2026, 11, 2, i)) for i in range(4)]

    def handler(request: httpx.Request):
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"data": {"items": rows}})

    _mock_web(monkeypatch, handler)
    cfg = {"url": "http://127.0.0.1/api", "auth": "bearer", "rows_path": "data.items"}
    t = service.test_connection("rest_json", cfg, {"token": "abc123"})
    assert t["ok"] and seen["auth"] == "Bearer abc123" and "utility_reading_id" in t["columns"] and len(t["sample"]) == 4
    cid = _save("rest_json", cfg, {"token": "abc123"}, columns=t["columns"])
    assert service.run(cid)["rows_stored"] == 4
    assert service.run(cid)["rows_stored"] == 0                               # the same rows again are skipped


@pytest.mark.parametrize("status,words", [(401, "sign-in"), (404, "404"), (500, "500")])
def test_rest_errors_are_explained(monkeypatch, status, words):
    _mock_web(monkeypatch, lambda r: httpx.Response(status))
    t = service.test_connection("rest_json", {"url": "http://127.0.0.1/api"}, {})
    assert not t["ok"] and words in t["message"]


def test_rest_not_json_and_redirects_are_explained(monkeypatch):
    _mock_web(monkeypatch, lambda r: httpx.Response(200, text="<html>hello</html>"))
    assert "JSON" in service.test_connection("rest_json", {"url": "http://127.0.0.1/x"}, {})["message"]
    _mock_web(monkeypatch, lambda r: httpx.Response(302, headers={"location": "http://127.0.0.1/new"}))
    assert "redirects" in service.test_connection("rest_json", {"url": "http://127.0.0.1/x"}, {})["message"]


def test_csv_link_is_stored_as_it_is(monkeypatch, clean):
    out = io.StringIO(newline="")
    w = csv.DictWriter(out, fieldnames=demo.COLUMNS)
    w.writeheader()
    w.writerows([_utility_row(i, dt.datetime(2026, 11, 3, i)) for i in range(6)])
    _mock_web(monkeypatch, lambda r: httpx.Response(200, content=out.getvalue().encode()))
    cfg = {"url": "http://127.0.0.1/energy.csv"}
    t = service.test_connection("csv_url", cfg, {})
    assert t["ok"] and len(t["columns"]) == 12
    cid = _save("csv_url", cfg)
    r1, r2 = service.run(cid), service.run(cid)
    assert r1["rows_stored"] == 6 and r2["rows_stored"] == 0 and "already there" in r2["message"]


# ------------------------------------------------------------------ demo gateway
def test_demo_gateway_pulls_fresh_hourly_readings_once(clean):
    t = service.test_connection("demo_gateway", {}, {})
    assert t["ok"] and len(t["sample"]) == 3
    cid = _save("demo_gateway", {})
    first = service.run(cid)
    assert first["ok"] and first["rows_stored"] == demo.INITIAL_HOURS * len(demo.PLANTS) * len(demo.UTILITIES)
    second = service.run(cid)
    assert second["ok"] and second["rows_stored"] == 0 and "Nothing new" in second["message"]
    with SessionLocal() as s:
        newest = s.execute(text("SELECT MAX(ts) FROM utility_readings WHERE utility_reading_id LIKE 'UT-DEMO-%'")).scalar()
    assert dt.datetime.now() - dt.timedelta(hours=2) < (newest if isinstance(newest, dt.datetime) else dt.datetime.fromisoformat(str(newest)))


def test_live_feed_target_explains_simulation_mode(clean):
    cid = _save("demo_gateway", {}, target="live_feed", mapping={"columns": {"tag": "utility_type", "value": "flow_rate"}})
    r = service.run(cid)
    assert r["ok"] and r["rows_stored"] == 0 and "simulation mode" in r["message"]


def test_a_failing_source_is_recorded_not_raised(monkeypatch, clean):
    _mock_web(monkeypatch, lambda r: httpx.Response(500))
    cid = _save("rest_json", {"url": "http://127.0.0.1/x"})
    r = service.run(cid)
    assert not r["ok"] and "500" in r["message"] and r["connector"]["status"] == "ERROR" and r["connector"]["last_ok_at"] is None


def test_a_system_that_needs_a_driver_says_so():
    t = service.test_connection("opcua", {"server": "opc.tcp://x:4840"}, {})
    assert not t["ok"] and "driver" in t["message"]
    with pytest.raises(ConnectorError):
        with SessionLocal() as s:
            service.create(s, {"kind": "opcua", "name": "x", "config": {"server": "s"}, "target": "utility"}, "t")


# ------------------------------------------------------------------ the API
def test_api_catalog_test_create_pull_and_delete(api, clean):
    cat = api.get("/api/connectors/catalog").json()
    kinds = {k["kind"]: k for k in cat["kinds"]}
    assert kinds["postgresql"]["available"] and kinds["rest_json"]["available"] and not kinds["opcua"]["available"]
    assert {t["key"] for t in cat["targets"]} >= {"live_feed", "utility", "energy"} and {s["seconds"] for s in cat["schedules"]} == {0, 60, 300, 900, 3600}
    assert api.post("/api/connectors/test", json={"kind": "demo_gateway"}).json()["ok"]
    assert api.post("/api/connectors/test", json={"kind": "postgresql", "config": {}}).json()["ok"] is False      # asks for the missing fields

    made = api.post("/api/connectors", json={"kind": "demo_gateway", "name": "Demo", "target": "utility", "schedule_s": 300,
                                              "columns": demo.COLUMNS}).json()
    assert made["run"]["ok"] and made["connector"]["status"] == "OK" and made["connector"]["schedule_label"] == "Every 5 minutes"
    cid = made["connector"]["id"]
    assert made["connector"]["next_run_at"]
    assert [c["id"] for c in api.get("/api/connectors").json()["connectors"]] == [cid]
    assert api.post(f"/api/connectors/{cid}/pull").json()["rows_stored"] == 0
    assert len(api.get(f"/api/connectors/{cid}/runs").json()["runs"]) == 2
    assert api.patch(f"/api/connectors/{cid}", json={"enabled": False}).json()["enabled"] is False
    assert api.delete(f"/api/connectors/{cid}").json() == {"deleted": cid}
    assert api.get("/api/connectors").json()["connectors"] == []
    assert api.post(f"/api/connectors/{cid}/pull").status_code == 404


def test_the_demo_endpoints_serve_rows_the_connectors_can_read(api):
    j = api.get("/api/demo/utility.json").json()["data"]["rows"]
    c = api.get("/api/demo/utility.csv").text
    assert len(j) == 24 * len(demo.PLANTS) * len(demo.UTILITIES) and c.splitlines()[0].split(",") == demo.COLUMNS
    assert TestClient(app).get("/api/connectors").status_code == 401           # the connectors themselves need a sign-in


# ------------------------------------------------------------------ the scheduler keeps its schedule in memory
def test_the_scheduler_does_not_query_the_database_while_idle(monkeypatch, clean):
    import datetime as dt
    from app.connectors import scheduler
    cid = _save("demo_gateway", {}, schedule_s=60)
    with SessionLocal() as s:                                               # a paused connection is never scheduled
        paused = service.create(s, {"kind": "demo_gateway", "name": "paused", "config": {}, "target": "utility", "schedule_s": 60}, "t")
        service.update(s, paused, {"enabled": False})
    scheduler.refresh()
    assert scheduler._due() == [cid]                                       # never pulled, so due now

    def no_database(*a, **k):
        raise AssertionError("the loop must not touch the database")

    monkeypatch.setattr(scheduler, "SessionLocal", no_database)
    assert scheduler._due() == [cid]
    scheduler._sched[cid] = (60, dt.datetime.now())                        # just pulled: not due for 60 s
    assert scheduler._due() == []
    scheduler._sched[cid] = (60, dt.datetime.now() - dt.timedelta(seconds=61))
    assert scheduler._due() == [cid]
    scheduler._sched.clear()
