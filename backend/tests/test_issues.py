"""Issues for the plant team: roster routing, mock history, auto-assignment, and how long / who / where answers."""
import datetime as dt

import pytest

from app.db.session import SessionLocal
from app.twin import catalog as cat
from app.twin import engine as eng_mod
from app.twin import issues as iss
from app.twin import mock, people as ppl
from app.twin.engine import ActionError, Engine
from tests.test_twin import T0, Clock


def _at(h: int) -> dt.datetime:
    return dt.datetime(2026, 11, 13, h, 0, 0)


@pytest.fixture
def roster():
    mock.seed(closed=6)
    iss.clear_people_cache()
    with SessionLocal() as s:
        people = ppl.load_people(s)
    yield people
    with SessionLocal() as s:
        mock.clear_mock(s)
        s.commit()
    iss.clear_people_cache()


@pytest.fixture
def eng(monkeypatch, roster):
    e = Engine(seed=7, start=T0)
    monkeypatch.setattr(eng_mod, "_engine", e)
    yield e
    cat.OVERRIDES.clear()


# ------------------------------------------------------------------ who goes
def test_routing_picks_the_team_member_on_shift_for_the_zone(roster):
    day = ppl.choose(roster, "COMPRESSED_AIR", "Compressor Room", _at(9))
    eve = ppl.choose(roster, "COMPRESSED_AIR", "Compressor Room", _at(16))
    night = ppl.choose(roster, "COMPRESSED_AIR", "Compressor Room", _at(2))
    assert (day["name"], eve["name"], night["name"]) == ("Ravi Kumar", "Suresh Babu", "Imran Sheikh")
    assert all(p["team"] == "Maintenance team" for p in (day, eve, night))


def test_gas_goes_to_the_safety_officer_and_falls_back_when_nobody_is_on_shift(roster):
    assert ppl.choose(roster, "GAS", "Gas Station", _at(9))["role"] == "Safety officer"
    night = ppl.choose(roster, "GAS", "Gas Station", _at(2))       # no safety officer works shift C
    assert night["team"] == "Utilities engineer"


def test_shift_boundaries():
    assert [ppl.shift_at(_at(h)) for h in (5, 6, 13, 14, 21, 22, 0)] == ["C", "A", "A", "B", "B", "C", "C"]


# ------------------------------------------------------------------ the mock history
def test_seed_creates_a_roster_closed_history_and_open_issues(eng):
    eng.reload_from_db()
    rows = iss.list_issues(eng, "all", limit=1000)
    mocked = [r for r in rows if r["source"] == "MOCK"]
    assert len(mocked) == 6 + len(mock.OPEN_PLAN)
    assert sum(r["open"] for r in mocked) == len(mock.OPEN_PLAN)
    for r in mocked:
        assert r["who"]["name"] and r["where"]["zone"] and r["todo"]
    closed = next(r for r in mocked if not r["open"])
    detail = iss.issue_detail(eng, closed["id"])
    actions = [e["action"] for e in detail["timeline"]]
    assert actions[0] == "detected" and "acknowledged" in actions and actions[-1] == "verified"
    assert detail["time"]["time_to_ack_s"] > 0 and detail["time"]["age_s"] > detail["time"]["time_to_ack_s"]


def test_open_issues_show_who_where_and_how_long(eng):
    eng.reload_from_db()
    open_rows = iss.list_issues(eng, "open")
    gas = next(r for r in open_rows if r["severity"] == "CRITICAL")
    assert gas["status"] == "OPEN" and gas["flags"]["unacknowledged_late"] and gas["flags"]["escalated"]
    assert 8 * 60 <= gas["time"]["age_s"] <= 10 * 60 and gas["where"]["zone"] == "Gas Station"
    old = next(r for r in open_rows if r["time"]["age_s"] > 3 * 86400)
    assert old["flags"]["overdue"] and old["time"]["overdue_by_s"] > 0
    assert open_rows[0]["flags"]["needs_attention"]               # attention first
    s = iss.summary(eng)
    assert s["open"] == len(mock.OPEN_PLAN) and s["by_severity"]["CRITICAL"] == 1 and s["overdue"] >= 1


def test_roster_view_counts_open_issues_per_person(eng):
    eng.reload_from_db()
    people = iss.roster(eng)
    assert sum(p["open_issues"] for p in people) == len(mock.OPEN_PLAN)
    assert any(p["on_shift_now"] for p in people)                 # the plant manager is on call 24 h


# ------------------------------------------------------------------ the engine and the mock data
def test_live_rules_leave_mock_issues_alone_and_reset_does_not_delete_them(eng):
    eng.reload_from_db()
    before = {a["id"]: (a["status"], len(a["events"])) for a in eng.alerts.values() if a["source"] == "MOCK"}
    clock = Clock(eng)
    clock.run(60)                                                  # long enough for any "condition cleared" or escalation
    assert {a["id"]: (a["status"], len(a["events"])) for a in eng.alerts.values() if a["source"] == "MOCK"} == before
    eng.reset_demo()
    assert {a["id"] for a in eng.alerts.values() if a["source"] == "MOCK"} == set(before)


def test_a_new_alert_goes_to_the_person_on_shift(eng):
    eng.sim.start("compressed_air_leak", 1.0)
    clock = Clock(eng)
    assert clock.until(lambda: any(a["type"] == "compressed_air_leakage" and a["source"] == "SIMULATED" for a in eng.alerts.values()), 300)
    a = next(a for a in eng.alerts.values() if a["type"] == "compressed_air_leakage" and a["source"] == "SIMULATED")
    assert a["assigned_to"] == "Suresh Babu"                       # maintenance, shift B at 14:00
    assert any(e["action"] == "auto_assigned" for e in a["events"])
    view = iss.issue_detail(eng, a["id"])
    assert view["who"]["name"] == "Suresh Babu" and view["who"]["role"] == "Maintenance technician" and view["who"]["on_shift_now"] in (True, False)
    eng.reset_demo()


def test_assign_accepts_a_person_from_the_roster_but_not_a_stranger(eng):
    eng.reload_from_db()
    new = next(a for a in eng.alerts.values() if a["status"] == "OPEN" and a["source"] == "MOCK")
    with pytest.raises(ActionError):
        eng.act(new["id"], "assign", "tester", "Somebody Else")
    out = eng.act(new["id"], "assign", "tester", "Karthik Menon")
    assert out["assigned_to"] == "Karthik Menon" and out["status"] == "ASSIGNED"


# ------------------------------------------------------------------ plant overview
def test_overview_shows_every_utility_and_marks_those_with_open_issues(eng):
    from app.twin import usage as use
    eng.reload_from_db()
    ov = use.overview(eng)
    assert [u["utility"] for u in ov["utilities"]] == cat.UTILITIES and ov["open"] == len(mock.OPEN_PLAN)
    by = {u["utility"]: u for u in ov["utilities"]}
    assert by["GAS"]["level"] == 3 and by["GAS"]["open_issues"] == 1 and "LEL" in by["GAS"]["reading"]
    assert by["STEAM"]["open_issues"] == 0 and by["STEAM"]["level"] == 0          # no open issue and live readings are normal
    assert 1 <= len(ov["attention"]) <= 3 and ov["attention"][0]["needs_attention"]


def test_usage_follows_the_open_issue_and_returns_the_shape_the_chart_needs(eng):
    from app.twin import usage as use
    eng.reload_from_db()
    now_h = dt.datetime.now().hour
    air = use.usage(eng, "COMPRESSED_AIR")                 # an air leak has been open for days
    assert len(air["today"]) == now_h + 1 and len(air["yesterday"]) == 24 and len(air["normal"]) == 24 and len(air["days"]) == 7
    assert air["today"][-1] > air["normal"][now_h]["hi"]                          # above the normal range while the issue is open
    assert air["issue"] and "leak" in air["note"].lower() and air["days"][-1]["partial"]
    steam = use.usage(eng, "STEAM")                        # nothing open: stays inside the normal range
    assert steam["issue"] is None and steam["normal"][now_h]["lo"] <= steam["today"][-1] <= steam["normal"][now_h]["hi"]
    assert steam["energy"] is None and air["energy"]["kwh"] > 0
    with pytest.raises(ActionError):
        use.usage(eng, "NOPE")


def test_agent_activity_lists_what_the_agent_did_and_counts_no_equipment_actions(eng):
    from app.twin import agent_activity as aa
    eng.reload_from_db()
    a = aa.activity(eng, days=30, limit=200)
    kinds = {f["kind"] for f in a["feed"]}
    assert {"detected", "escalated", "verified"} <= kinds and a["actions_on_equipment"] == 0
    assert a["feed"] == sorted(a["feed"], key=lambda f: f["ts"], reverse=True)
    detected = next(f for f in a["feed"] if f["kind"] == "detected")
    assert detected["code"].startswith("ALT-") and "Sent to" in detected["text"]            # the person it was handed to is named
    assert set(a["today"]) == {"detected", "handed_off", "escalated", "verified"} and all(v >= 0 for v in a["today"].values())
    assert len(aa.activity(eng, days=30, limit=3)["feed"]) == 3


def test_a_reading_above_its_limit_shows_up_as_such_not_as_a_usage_change(eng):
    from app.twin import usage as use
    eng.reload_from_db()
    gas = use.usage(eng, "GAS")                                   # the critical gas issue is a sensor reading above its limit
    sig = gas["signal"]
    h = gas["now_hour"]
    assert sig and sig["lo"] == 0 and sig["hi"] == 5 and sig["actual"] > sig["hi"] and len(sig["points"]) == h + 1
    assert sig["points"][-1] > sig["hi"]                           # outside its limit now
    assert any(p <= sig["hi"] for p in sig["points"][:-1]) or h == 0   # and inside it before the issue started
    assert "outside its limit" in gas["note"] and "Usage itself is normal" in gas["note"]
    assert gas["normal"][h]["lo"] <= gas["today"][-1] <= gas["normal"][h]["hi"]       # the usage line is not distorted
    assert use.usage(eng, "STEAM")["signal"] is None
    air = use.usage(eng, "COMPRESSED_AIR")                         # a real usage problem keeps its usage story and also gets its reading
    assert air["today"][-1] > air["normal"][air["now_hour"]]["hi"] and air["signal"]["points"]
