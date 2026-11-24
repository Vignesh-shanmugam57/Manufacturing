import json

import pytest

from app.agent.tools import TOOLS, run_sql
from app.services import alerts as al
from app.services import analytics as an
from app.services import monitor


def test_resolve_aliases_and_errors(session):
    assert an.resolve_utility(session, "compressed air") == "COMPRESSED_AIR"
    assert an.resolve_utility(session, "air") == "COMPRESSED_AIR"
    assert an.resolve_utility(session, "") is None and an.resolve_utility(session, "all") is None
    assert an.resolve_zone(session, "smt") == "SMT"
    assert an.resolve_plant(session, "p1") == "P1"
    with pytest.raises(ValueError, match="Available: COMPRESSED_AIR, HVAC"):
        an.resolve_utility(session, "steam")


def test_data_overview_reports_quality_problems(session):
    o = an.data_overview(session)
    assert o["plants"] == ["P1", "P2"] and o["utility_types"] == ["COMPRESSED_AIR", "HVAC"]
    assert o["as_of"].isoformat() == "2026-09-30T23:00:00"
    text = " ".join(o["data_quality"])
    assert "consumption_unit changes" in text          # the factory mixes m3/L/kWh on purpose
    assert "PRESSURE_LOW alarms do not coincide" in text


def test_planted_flow_increase_is_found_and_nothing_else(session):
    res = an.detect_abnormal_usage(session, days=5)
    shifts = [a for a in res["anomalies"] if a["type"] == "level_shift" and a["metric"] == "flow"]
    top = shifts[0]
    assert (top["utility_type"], top["plant_id"], top["zone"], top["direction"]) == ("COMPRESSED_AIR", "P1", "SMT", "up")
    assert top["severity"] == "HIGH" and 35 < top["evidence"]["change_pct"] < 45
    assert "air leaks" in top["likely_cause"] and top["recommendation"]
    assert all(a["utility_type"] == "COMPRESSED_AIR" for a in res["anomalies"] if a["metric"] == "flow")
    assert not [a for a in res["anomalies"] if a["utility_type"] == "HVAC" and a["metric"] != "alarms"]


def test_quiet_series_reports_no_anomaly(session):
    res = an.detect_abnormal_usage(session, days=5, utility_type="hvac", plant_id="p1")
    assert res["anomaly_count"] == 0 and res["conclusion"].startswith("No statistically abnormal")
    assert an.detect_abnormal_usage(session, days=3, utility_type="COMPRESSED_AIR", zone="TEST")["anomaly_count"] == 0


def test_downtime_link_found_for_hvac_only(session):
    res = an.downtime_correlation(session, window_hours=2)
    by = {x["utility_type"]: x for x in res["by_utility_type"]}
    assert by["HVAC"]["verdict"] == "possible link" and by["HVAC"]["lift"] > 3
    assert by["COMPRESSED_AIR"]["verdict"] == "no meaningful link"
    assert "HVAC" in res["conclusion"]
    assert res["downtime_summary"]["events"] == 90 and res["downtime_summary"]["by_reason"]


def test_downtime_link_absent_for_the_other_plant(session):
    res = an.downtime_correlation(session, plant_id="P1", utility_type="HVAC")
    assert res["overall"]["verdict"] == "no meaningful link"


def test_trends_direction(session):
    t = an.consumption_trends(session, utility_type="COMPRESSED_AIR", plant_id="P1", zone="SMT", period="day", periods=8)
    g = t["groups"][0]
    assert g["direction"] == "up" and len(g["series"]) == 8
    assert g["series"][-1]["avg_flow"] > 90 > g["series"][0]["avg_flow"]
    zones = an.consumption_trends(session, group_by="zone")
    assert {x["group"] for x in zones["groups"]} == {"SMT", "TEST"}
    with pytest.raises(ValueError):
        an.consumption_trends(session, period="month")


def test_efficiency_flags_demand_that_ignores_idle_machines(session):
    res = an.efficiency_opportunities(session)
    assert any(r["action"].startswith("Add idle-time") for r in res["recommendations"])
    idle = next(f for f in res["findings"] if f["check"] == "demand_vs_idle_machines")["results"]
    assert idle and all(0.85 < x["demand_ratio_idle_vs_busy"] < 1.15 for x in idle)
    assert "Upper bound" in res["recommendations"][0]["why"]


def test_health_board(session):
    hb = an.health_board(session)
    st = {u["utility_type"]: u["status"] for u in hb["utilities"]}
    assert st["COMPRESSED_AIR"] == "ALARM" and hb["overall_status"] == "ALARM"
    assert hb["downtime_link"]["by_utility_type"] and hb["efficiency"]["recommendations"]


def test_alert_dedup_workflow_and_verification(session):
    a, created = al.create_alert(session, utility_type="air", plant_id="p1", zone="smt", title="Flow up 40%",
                                 severity="high", recommendation="Leak survey", category="t_leak")
    assert created and a.utility_type == "COMPRESSED_AIR" and (a.plant_id, a.zone) == ("P1", "SMT")
    again, created2 = al.create_alert(session, utility_type="COMPRESSED_AIR", plant_id="P1", zone="SMT",
                                      title="dup", severity="HIGH", category="t_leak")
    assert not created2 and again.id == a.id
    with pytest.raises(ValueError):
        al.create_alert(session, utility_type="COMPRESSED_AIR", title="x", severity="URGENT")
    with pytest.raises(ValueError):
        al.update_alert_status(session, a.id, "VERIFIED")          # only the telemetry check may verify
    assert al.update_alert_status(session, a.id, "ACKNOWLEDGED", "on it")["status"] == "ACKNOWLEDGED"
    al.update_alert_status(session, a.id, "RESOLVED", "fixed?")
    v = al.verify_return_to_normal(session, a.id, hours=48)        # flow is still 40 % up -> must not verify
    assert v["normal"] is False and v["status"] == "RESOLVED" and v["still_abnormal"]

    b, _ = al.create_alert(session, utility_type="HVAC", plant_id="P1", zone="TEST", title="Check",
                           severity="LOW", category="t_check")
    assert al.verify_return_to_normal(session, b.id, hours=240)["status"] == "OPEN"
    al.update_alert_status(session, b.id, "RESOLVED", "done")
    v = al.verify_return_to_normal(session, b.id, hours=48)
    assert v["normal"] is True and v["status"] == "VERIFIED"
    with pytest.raises(ValueError):
        al.verify_return_to_normal(session, 999999)


def test_scan_raises_deduplicated_alerts(session):
    first = monitor.run_scan(session)
    cats = {a["category"] for a in first["created"]}
    assert "level_shift:flow" in cats and "downtime_link" in cats
    assert all(a["assigned_to"] in ("facilities", "maintenance") for a in first["created"])
    second = monitor.run_scan(session)
    assert second["created_count"] == 0 and second["already_open_count"] >= 2


def test_run_sql_is_read_only_and_hides_user_tables():
    ok = run_sql.invoke({"query": "SELECT utility_type, count(*) AS n FROM utility_readings GROUP BY utility_type"})
    assert "COMPRESSED_AIR" in ok
    assert run_sql.invoke({"query": "DELETE FROM utility_readings"}).startswith("ERROR")
    assert run_sql.invoke({"query": "SELECT 1; DROP TABLE utility_readings"}).startswith("ERROR")
    assert "not queryable" in run_sql.invoke({"query": "SELECT * FROM users"})
    assert "not queryable" in run_sql.invoke({"query": "SELECT * FROM chat_messages"})


def test_every_analysis_tool_returns_valid_json():
    by_name = {t.name: t for t in TOOLS}
    for name, args in [("get_data_overview", {}), ("get_utility_health_board", {}),
                       ("get_consumption_trends", {"utility_type": "hvac", "period": "week"}),
                       ("detect_abnormal_usage", {"days": 5}), ("get_downtime_correlation", {"plant_id": "P2"}),
                       ("get_efficiency_recommendations", {})]:
        json.loads(by_name[name].invoke(args))


def test_a_series_with_no_recent_readings_is_skipped_not_a_crash():
    """After a gap in the data (for example a source that stopped for weeks) a series can have history but nothing recent."""
    from app.services import analytics as an
    assert an._pct(None, 5.0) is None and an._pct(5.0, None) is None and an._pct(6.0, 5.0) == pytest.approx(20.0)
    assert an._finding("COMPRESSED_AIR", "IN-KA-01", "SMT", "flow", [10.0, 11.0, 12.0], [], None, 3, 0) is None
