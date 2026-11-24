"""The chat agent's plant tools: they answer from the same issues, roster and usage the rest of the app shows."""
import json

import pytest

from app.agent import agent as agent_mod
from app.agent import plant_tools as pt
from app.agent.tools import TOOLS
from tests.test_issues import eng, roster  # noqa: F401  (fixtures: a seeded roster and incident history, and an engine that has loaded them)


@pytest.fixture
def loaded(eng):                        # noqa: F811
    eng.reload_from_db()
    return eng


def call(tool, **kw):
    out = tool.invoke(kw)
    try:
        return json.loads(out)
    except ValueError:
        return out


def test_the_tools_are_registered_and_described_to_the_model():
    names = {t.name for t in TOOLS}
    assert {t.name for t in pt.PLANT_TOOLS} <= names and len(pt.PLANT_TOOLS) == 6
    assert "get_plant_status" in agent_mod.TOOL_DOC and "list_open_issues" in agent_mod.SYSTEM_PROMPT


def test_plant_status_covers_every_utility_and_the_urgent_issues(loaded):
    s = call(pt.get_plant_status)
    assert len(s["utilities"]) == 7 and s["open_issues"] >= 1
    gas = next(u for u in s["utilities"] if u["utility"] == "Gas")
    assert gas["status"] == "Critical" and s["needs_attention_first"][0]["severity"] == "CRITICAL"


def test_open_issues_say_who_where_how_long_and_what_to_do(loaded):
    r = call(pt.list_open_issues)
    first = r["issues"][0]
    for key in ("owner", "zone", "equipment", "open_for", "what_to_do", "reading", "stage"):
        assert first[key]
    assert call(pt.list_open_issues, severity="CRITICAL")["count"] == 1
    assert call(pt.list_open_issues, utility="chilled water")["issues"][0]["zone"] == "Chiller Plant"
    assert call(pt.list_open_issues, zone="Nowhere") == "No open issues match."


def test_one_issue_in_full_by_code_or_number(loaded):
    code = call(pt.list_open_issues, severity="CRITICAL")["issues"][0]["code"]
    full = call(pt.get_issue, issue=code)
    assert full["code"] == code and full["timeline"] and full["notified"] and full["task"] and full["cause"]
    assert call(pt.get_issue, issue=str(int(code[-5:])))["code"] == code        # the bare number works too
    assert call(pt.get_issue, issue="ALT-99999").startswith("No issue found")
    assert call(pt.get_issue, issue="no number here").startswith("ERROR")


def test_team_on_shift_respects_zone_and_team_and_flags_handovers(loaded):
    t = call(pt.get_team_on_shift)
    assert t["on_shift"] and any(p["name"] == "Lakshmi Narayanan" for p in t["on_shift"])        # the plant manager is on call 24 h
    safety = call(pt.get_team_on_shift, zone="Gas Station", team="safety")
    assert all(p["team"] == "Safety officer" for p in safety["on_shift"])
    assert isinstance(t["shift_ended_but_still_own_open_issues"], list)


def test_usage_tool_places_today_against_the_normal_range(loaded):
    air = call(pt.get_usage_vs_normal, utility="compressed air")                  # an air leak has been open for days
    assert air["position"] == "above the normal range" and air["related_issue"] and "mock" in air["source"]
    steam = call(pt.get_usage_vs_normal, utility="STEAM")
    assert steam["position"] == "within the normal range"
    assert call(pt.get_usage_vs_normal, utility="plasma").startswith("ERROR")


def test_issue_history_summarises_response_and_repeat_offenders(loaded):
    h = call(pt.get_issue_history, days=30)
    assert h["closed"] >= 6 and h["issues_raised"] >= h["closed"] and h["most_issues_by_equipment"] and h["average_time_to_close"] != "n/a"


def test_the_chat_agent_has_no_tool_that_raises_or_changes_issues():
    names = {t.name for t in TOOLS}
    assert not names & {"raise_alert", "run_monitoring_scan", "verify_return_to_normal", "list_alerts"}
    assert "raise_alert" not in agent_mod.SYSTEM_PROMPT and "run_monitoring_scan" not in agent_mod.SYSTEM_PROMPT
