"""Digital twin: catalog, detection, alert lifecycle, verification, escalation, ingest. Time is simulated."""
import datetime as dt

import pytest

from app.twin import catalog as cat
from app.twin import engine as eng_mod
from app.twin.engine import ActionError, Engine
from app.twin.simulator import SCENARIOS

T0 = dt.datetime(2026, 11, 13, 14, 0, 0)


@pytest.fixture
def eng(monkeypatch):
    e = Engine(seed=7, start=T0)
    monkeypatch.setattr(eng_mod, "_engine", e)
    yield e
    cat.OVERRIDES.clear()


class Clock:
    def __init__(self, e: Engine):
        self.e, self.now = e, T0

    def run(self, seconds: int) -> None:
        for _ in range(seconds):
            self.now += dt.timedelta(seconds=1)
            self.e.tick(self.now, 1.0)
        self.e.drain()

    def until(self, cond, limit: int = 240) -> bool:
        for _ in range(limit):
            self.run(1)
            if cond():
                return True
        return False


def _alert(e: Engine, kind: str):
    return next((a for a in e.alerts.values() if a["type"] == kind), None)


# ------------------------------------------------------------------ catalog
def test_catalog_covers_all_seven_utilities_with_nested_limits():
    assert {e.utility for e in cat.EQUIPMENT} == set(cat.UTILITIES) and len(cat.UTILITIES) == 7
    for tag, (e, s) in cat.SPEC.items():
        if s.cumulative or s.normal is None:
            continue
        n, w, c = cat.bands(tag)
        lo = lambda b: float("-inf") if b[0] is None else b[0]
        hi = lambda b: float("inf") if b[1] is None else b[1]
        assert lo(c) <= lo(w) <= lo(n) <= hi(n) <= hi(w) <= hi(c), tag
        assert cat.level_of(tag, s.nominal) == 0, f"{tag} nominal {s.nominal} must be normal"


def test_level_of_follows_the_bands():
    t = "CA-HDR-A.pressure_bar"                 # normal 6.4-7.2, warn 6.1-7.5, crit 5.6-8.0
    assert [cat.level_of(t, v) for v in (6.8, 6.3, 5.8, 5.0)] == [0, 1, 2, 3]


# ------------------------------------------------------------------ normal operation
def test_normal_operation_raises_no_alert(eng):
    Clock(eng).run(150)
    assert eng.alerts == {} and max(eng.eq_level.values()) < 2
    k = eng.kpis()
    assert k["alarms_active"] == 0 and k["availability_pct"] == 100.0 and k["energy_kwh"] > 0


# ------------------------------------------------------------------ the required demonstration
def test_compressed_air_leak_end_to_end(eng):
    c = Clock(eng)
    c.run(100)                                                      # a baseline
    eng.sim.start("compressed_air_leak")
    assert c.until(lambda: _alert(eng, "compressed_air_leakage") is not None), "leak was not detected"
    assert c.until(lambda: _alert(eng, "compressed_air_leakage")["severity"] in ("MAJOR", "CRITICAL")), "severity never reached MAJOR"
    a = _alert(eng, "compressed_air_leakage")
    assert a["severity"] in ("MAJOR", "CRITICAL") and a["status"] == "OPEN" and a["equipment_id"] == "CA-HDR-A"
    assert a["certainty"] == "PROBABLE" and 0.5 <= a["confidence"] <= 0.95          # never presented as a confirmed leak
    assert "bar" in a["actual"] and "6.4 - 7.2" in a["expected"]
    assert "Assembly Line A" in a["consumers"] and eng.eq_level["CA-HDR-A"] >= 2
    k = eng.kpis()
    assert k["leaks_suspected"] == 1 and k["leak_est_m3min"] > 0 and k["alarms_active"] == 1
    assert {x["tag"] for x in a["evidence"]} >= {"CA-HDR-A.pressure_bar", "CA-HDR-A.flow_m3min", "CA-CMP-01.load_pct"}
    steps = [s["key"] for s in a["analysis"]["steps"]]
    assert steps == ["collected", "validated", "mapped", "detected", "root_cause", "impact", "recommended", "alerted", "verification"]
    task = next(m for m in eng.maint.values() if m["alert_id"] == a["id"])
    assert task["status"] == "PENDING" and task["priority"] in ("HIGH", "URGENT")
    assert {n["recipient"] for n in eng.notifications if n["alert_id"] == a["id"]} >= {"facilities", "maintenance"}
    assert [e["action"] for e in a["events"]][:3] == ["detected", "analysis_completed", "notified"]

    # the workflow: acknowledge -> assign -> investigate -> corrective action -> verify
    with pytest.raises(ActionError):
        eng.act(a["id"], "verify", "Sam")                            # nothing to verify before corrective action
    eng.act(a["id"], "acknowledge", "Sam")
    with pytest.raises(ActionError):
        eng.act(a["id"], "assign", "Sam", assignee="Nobody")
    eng.act(a["id"], "assign", "Sam", assignee="Maintenance team")
    eng.act(a["id"], "investigate", "Lee", comment="On site")
    eng.act(a["id"], "comment", "Lee", comment="Hissing heard near the Hall A drop leg")
    with pytest.raises(ActionError):
        eng.act(a["id"], "corrective_action", "Lee", comment="  ")
    eng.act(a["id"], "corrective_action", "Lee", comment="Replaced a failed quick coupling")
    assert eng.alerts[a["id"]]["status"] == "CORRECTIVE_ACTION"
    assert eng.maint[task["id"]]["status"] == "COMPLETED"            # task done, but the alert is NOT closed yet
    with pytest.raises(ActionError) as bad:
        eng.act(a["id"], "verify", "agent")                          # telemetry is still abnormal
    assert "Not back to normal" in str(bad.value) and eng.alerts[a["id"]]["status"] == "CORRECTIVE_ACTION"

    assert eng.sim.fix()                                              # simulated corrective action restores telemetry
    assert c.until(lambda: eng.alerts[a["id"]]["status"] == "VERIFIED", limit=240), "agent did not verify recovery"
    done = eng.alerts[a["id"]]
    assert done["closed_at"] and "inside the engineering limits" in done["verification_note"]
    assert eng.maint[task["id"]]["status"] == "VERIFIED" and eng.eq_level["CA-HDR-A"] == 0
    assert ("CA-HDR-A", "compressed_air_leakage") not in eng.active
    actions = [e["action"] for e in done["events"]]
    for expected in ("detected", "acknowledged", "assigned", "investigating", "comment", "corrective_action", "verified"):
        assert expected in actions, expected
    assert actions.index("acknowledged") < actions.index("corrective_action") < actions.index("verified")
    assert done["analysis"]["steps"][-1]["ok"] is True
    assert eng.meta["CA-HDR-A"]["last_maintenance"] == dt.date.today()   # maintenance dates move on after verification


def test_recovery_without_a_corrective_action_never_auto_closes(eng):
    c = Clock(eng)
    c.run(100)
    eng.sim.start("compressed_air_leak")
    assert c.until(lambda: _alert(eng, "compressed_air_leakage") is not None)
    a = _alert(eng, "compressed_air_leakage")
    eng.sim.fix()
    c.run(120)
    got = eng.alerts[a["id"]]
    assert got["condition_cleared"] is True and got["status"] == "OPEN"
    assert any(e["action"] == "condition_cleared" for e in got["events"])


# ------------------------------------------------------------------ every utility can be demonstrated
@pytest.mark.parametrize("name", list(SCENARIOS))
def test_every_scenario_is_detected_on_the_right_utility(eng, name):
    c = Clock(eng)
    c.run(100)
    eng.sim.start(name, 1.5 if name == "gas_abnormal_consumption" else 1.0)
    utility = SCENARIOS[name]["utility"]
    assert c.until(lambda: any(a["utility"] == utility for a in eng.alerts.values())), f"{name} not detected"
    a = next(a for a in eng.alerts.values() if a["utility"] == utility)
    assert a["severity"] in ("WARNING", "MAJOR", "CRITICAL") and a["recommendation"] and a["actual"] and a["expected"]
    assert a["certainty"] in ("PROBABLE", "CONFIRMED")


def test_gas_safety_alarm_is_critical_and_escalates(eng):
    c = Clock(eng)
    c.run(100)
    eng.sim.start("gas_abnormal_consumption", 1.5)
    assert c.until(lambda: _alert(eng, "gas_abnormal_consumption") is not None)
    assert c.until(lambda: _alert(eng, "gas_abnormal_consumption")["severity"] == "CRITICAL"), "gas safety alarm never became CRITICAL"
    a = _alert(eng, "gas_abnormal_consumption")
    assert a["severity"] == "CRITICAL" and "Gas safety alarm" in a["title"]
    assert {n["recipient"] for n in eng.notifications if n["alert_id"] == a["id"]} >= {"safety_officer", "plant_manager"}
    c.run(130)                                                        # nobody acknowledges
    esc = [n for n in eng.notifications if n["alert_id"] == a["id"] and n["escalated"]]
    assert esc and esc[0]["recipient"] == "plant_manager"
    assert any(e["action"] == "escalated" for e in eng.alerts[a["id"]]["events"])


# ------------------------------------------------------------------ real data path and offline handling
def test_live_mode_ingest_validates_and_marks_silent_equipment_offline(eng):
    eng.set_mode("live")
    try:
        c = Clock(eng)
        n, rejected = eng.ingest({"CA-HDR-A.pressure_bar": 6.8, "NOPE.tag": 1.0, "CA-HDR-A.flow_m3min": float("nan")}, c.now, "LIVE")
        assert n == 1 and set(rejected) == {"NOPE.tag", "CA-HDR-A.flow_m3min"}
        c.run(20)                                                     # no more readings arrive
        assert eng.eq_level["CA-HDR-A"] == 4 and cat.LEVELS[4] == "OFFLINE"
        assert eng.source_label == "LIVE"
        with pytest.raises(ActionError):
            eng.set_mode("something")
    finally:
        eng.set_mode("simulation")


# ------------------------------------------------------------------ demo reset and limits
def test_reset_demo_removes_simulated_records_only(eng):
    c = Clock(eng)
    c.run(100)
    eng.sim.start("compressed_air_leak")
    assert c.until(lambda: _alert(eng, "compressed_air_leakage") is not None)
    assert eng.reset_demo()["alerts_deleted"] >= 1
    assert eng.alerts == {} and eng.maint == {} and eng.sim.state()["active"] is None


def test_limits_can_be_changed_but_must_nest(eng):
    t = "CA-HDR-A.pressure_bar"
    before = cat.bands(t)[0]
    eng.set_limit(t, "normal", 6.5, 7.1, "Sam")
    assert cat.bands(t)[0] == (6.5, 7.1) and cat.level_of(t, 6.45) == 1
    with pytest.raises(ActionError):
        eng.set_limit(t, "normal", 5.0, 7.1, "Sam")                   # normal band would leave the warning band
    with pytest.raises(ActionError):
        eng.set_limit(t, "normal", 7.0, 6.0, "Sam")
    cat.OVERRIDES.pop(t, None)
    assert cat.bands(t)[0] == before


# ------------------------------------------------------------------ API
def test_api_catalog_alert_actions_and_safety(eng):
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app) as client:
        user = client.post("/api/users/login", json={"email": "twin.tester@example.com", "name": "Twin Tester", "role": "Utilities engineer"}).json()
        h = {"X-User-Id": user["id"]}
        assert client.get("/api/twin/catalog").status_code == 401
        cat_json = client.get("/api/twin/catalog", headers=h).json()
        assert len(cat_json["utilities"]) == 7 and len(cat_json["scenarios"]) == 7 and cat_json["equipment"]
        snap = client.get("/api/twin/snapshot", headers=h).json()
        assert snap["source"] == "SIMULATED" and len(snap["values"]) == len(cat.TAGS) and snap["levels"]["CA-HDR-A"] == 0
        # there is no control surface: nothing in the API can operate equipment
        routes = set(app.openapi()["paths"])
        assert not any(w in p for p in routes for w in ("setpoint", "valve", "start_pump", "stop_pump"))
        c = Clock(eng)
        c.run(100)
        assert client.post("/api/twin/scenarios/start", json={"name": "compressed_air_leak"}, headers=h).status_code == 200
        assert client.post("/api/twin/scenarios/start", json={"name": "water_leak"}, headers=h).status_code == 400   # one at a time
        assert c.until(lambda: _alert(eng, "compressed_air_leakage") is not None)
        a = _alert(eng, "compressed_air_leakage")
        r = client.post(f"/api/twin/alerts/{a['id']}/actions", json={"action": "acknowledge"}, headers=h)
        assert r.status_code == 200 and r.json()["status"] == "ACKNOWLEDGED"
        r = client.post(f"/api/twin/alerts/{a['id']}/actions", json={"action": "corrective_action", "comment": ""}, headers=h)
        assert r.status_code == 400
        ev = client.get(f"/api/twin/alerts/{a['id']}", headers=h).json()["events"]
        assert any("Twin Tester" in e["actor"] for e in ev if e["action"] == "acknowledged")        # who did it is recorded
        series = client.get("/api/twin/series", params={"tags": "CA-HDR-A.pressure_bar", "minutes": 5, "step": 1}, headers=h).json()
        assert len(series["series"]["CA-HDR-A.pressure_bar"]) > 50
        assert client.post("/api/twin/ingest", json={"readings": [{"tag": "CA-HDR-A.pressure_bar", "value": 6.8}]}, headers=h).status_code == 400  # simulation mode
        client.post("/api/twin/scenarios/reset", headers=h)
