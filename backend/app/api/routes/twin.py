"""Digital twin API: live telemetry stream, equipment, alerts with an audit trail, maintenance, scenarios, limits.

All reads come from the engine's memory (instant). Every write that changes an alert or a task goes through the
engine so the audit trail is complete. There is no endpoint that operates equipment.
"""
import asyncio
import json
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, get_current_user
from app.twin import agent_activity as aa, catalog as cat, issues as iss, mock, usage as use
from app.db.session import SessionLocal
from app.twin.engine import TEAMS, ActionError, get_engine
from app.twin.simulator import SCENARIOS

router = APIRouter(prefix="/twin", tags=["digital twin"], dependencies=[Depends(get_current_user)])


def _actor(user) -> str:
    return f"{user.name} ({user.role or 'user'})"


@router.get("/catalog")
def catalog():
    out = cat.catalog_json()
    out["teams"] = TEAMS
    out["scenarios"] = [{"id": k, "title": v["title"], "utility": v["utility"], "equipment": v["equipment"], "text": v["text"]}
                        for k, v in SCENARIOS.items()]
    return out


@router.get("/snapshot")
def snapshot():
    return get_engine().snapshot()


@router.get("/stream")
async def stream(request: Request):
    """Server-Sent Events: one snapshot of every sensor, equipment status and the KPIs per second."""
    eng = get_engine()

    async def gen():
        yield ": connected\n\n"
        while not await request.is_disconnected():
            yield f"event: snapshot\ndata: {json.dumps(eng.snapshot())}\n\n"
            await asyncio.sleep(1.0)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/series")
def series(tags: str = Query(..., description="comma separated tags"), minutes: int = 10, step: int = 2):
    wanted = [t for t in tags.split(",") if t][:200]
    return {"minutes": minutes, "step_s": step, "series": get_engine().series(wanted, minutes, step)}


@router.get("/kpis")
def kpis():
    return get_engine().kpis()


@router.get("/equipment")
def equipment_list():
    return {"equipment": get_engine().equipment_list()}


@router.get("/equipment/{equipment_id}")
def equipment(equipment_id: str):
    return get_engine().equipment_detail(equipment_id)


@router.get("/alerts")
def alerts(status: Literal["all", "active", "closed"] = "all", limit: int = 200):
    rows = get_engine().list_alerts(status, limit)
    return {"count": len(rows), "alerts": [{k: v for k, v in a.items() if k not in ("analysis",)} for a in rows]}


@router.get("/alerts/{alert_id}")
def alert(alert_id: int):
    a = get_engine().alerts.get(alert_id)
    if a is None:
        raise ActionError(f"Alert {alert_id} not found.")
    return a


class AlertAction(BaseModel):
    action: Literal["acknowledge", "assign", "investigate", "comment", "corrective_action", "verify", "reopen"]
    assignee: str | None = None
    comment: str | None = Field(default=None, max_length=1000)


@router.post("/alerts/{alert_id}/actions")
def alert_action(alert_id: int, body: AlertAction, user: CurrentUser):
    return get_engine().act(alert_id, body.action, _actor(user), body.assignee, body.comment)


@router.get("/maintenance")
def maintenance():
    eng = get_engine()
    with eng.lock:
        rows = sorted(eng.maint.values(), key=lambda m: m["id"], reverse=True)
        for m in rows:
            m["equipment_name"] = cat.BY_ID[m["equipment_id"]].name
            al = eng.alerts.get(m["alert_id"])
            m["alert_code"] = al["code"] if al else None
    return {"count": len(rows), "tasks": rows}


class MaintAction(BaseModel):
    action: Literal["assign", "start", "complete", "verify"]
    assignee: str | None = None
    notes: str | None = Field(default=None, max_length=1000)


@router.post("/maintenance/{task_id}/actions")
def maintenance_action(task_id: int, body: MaintAction, user: CurrentUser):
    eng = get_engine()
    task = eng.maint.get(task_id)
    if task is None or task["alert_id"] is None:
        raise ActionError(f"Maintenance task {task_id} not found.")
    mapping = {"assign": "assign", "start": "investigate", "complete": "corrective_action", "verify": "verify"}
    if body.action in ("assign", "start") and (eng.alerts[task["alert_id"]]["status"] == "OPEN"):
        eng.act(task["alert_id"], "acknowledge", _actor(user), comment="Acknowledged from the maintenance task.")
    eng.act(task["alert_id"], mapping[body.action], _actor(user), body.assignee, body.notes)
    return eng.maint[task_id]


@router.get("/notifications")
def notifications():
    return {"notifications": list(get_engine().notifications)[:100]}


@router.get("/audit")
def audit(limit: int = 300):
    eng = get_engine()
    with eng.lock:
        rows = [{**e, "alert_id": a["id"], "alert_code": a["code"], "title": a["title"], "equipment_id": a["equipment_id"]}
                for a in eng.alerts.values() for e in a["events"]]
    rows.sort(key=lambda r: r["ts"], reverse=True)
    return {"count": len(rows), "events": rows[:limit]}


# ---------------------------------------------------------------- scenarios (demo) and mode
class ScenarioStart(BaseModel):
    name: str
    intensity: float = Field(default=1.0, ge=0.3, le=2.0)


@router.get("/scenarios")
def scenarios():
    eng = get_engine()
    return {"state": eng.sim.state(), "mode": eng.mode,
            "scenarios": [{"id": k, "title": v["title"], "utility": v["utility"], "equipment": v["equipment"], "text": v["text"]} for k, v in SCENARIOS.items()]}


@router.post("/scenarios/start")
def scenario_start(body: ScenarioStart):
    eng = get_engine()
    if eng.mode != "simulation":
        raise ActionError("Scenarios only run in simulation mode.")
    if eng.sim.scenario:
        raise ActionError("A scenario is already running. Simulate the corrective action or reset the demo first.")
    eng.sim.start(body.name, body.intensity)
    return eng.sim.state()


@router.post("/scenarios/fix")
def scenario_fix():
    """DEMO only: the simulated telemetry returns to normal, as if a technician had fixed the fault."""
    eng = get_engine()
    if not eng.sim.fix():
        raise ActionError("There is no active simulated fault to correct.")
    return eng.sim.state()


@router.post("/scenarios/reset")
def scenario_reset():
    return get_engine().reset_demo()


class ModeBody(BaseModel):
    mode: Literal["simulation", "live"]


@router.put("/mode")
def set_mode(body: ModeBody):
    return get_engine().set_mode(body.mode)


# ---------------------------------------------------------------- real data in
class Reading(BaseModel):
    tag: str
    value: float


class IngestBody(BaseModel):
    readings: list[Reading] = Field(max_length=2000)


@router.post("/ingest")
def ingest(body: IngestBody):
    """The real integration point: a SCADA/BMS/PLC gateway pushes {"tag": "CA-HDR-A.pressure_bar", "value": 6.8}.
    Accepted in live mode (in simulation mode the simulator owns the tags)."""
    import datetime as dt
    eng = get_engine()
    if eng.mode != "live":
        raise ActionError("Ingest is only accepted in live mode. Switch the mode on the Configuration page first.")
    n, rejected = eng.ingest({r.tag: r.value for r in body.readings}, dt.datetime.now(), "LIVE")
    return {"accepted": n, "rejected": rejected}


# ---------------------------------------------------------------- configuration
@router.get("/limits")
def limits():
    return {"sensors": [{"tag": t, "equipment": e.name, "equipment_id": e.id, "utility": e.utility, "label": s.label, "unit": s.unit,
                         "limits": {k: list(b) if b else None for k, b in zip(("normal", "warn", "crit"), cat.bands(t))},
                         "overridden": t in cat.OVERRIDES}
                        for t, (e, s) in cat.SPEC.items() if not s.cumulative and s.normal is not None]}


class LimitBody(BaseModel):
    tag: str
    band: Literal["normal", "warn", "crit"]
    lo: float | None = None
    hi: float | None = None


@router.put("/limits")
def set_limit(body: LimitBody, user: CurrentUser):
    return get_engine().set_limit(body.tag, body.band, body.lo, body.hi, _actor(user))


@router.get("/settings")
def settings():
    eng = get_engine()
    return {"mode": eng.mode, "tariffs": eng.tariffs, "teams": TEAMS, "ingested": eng.ingested, "rejected": eng.rejected,
            "escalation": {"CRITICAL": "notify plant manager after 120 s unacknowledged", "MAJOR": "notify operations supervisor after 300 s unacknowledged"},
            "notification_roles": {"WARNING": ["maintenance"], "MAJOR": ["facilities", "maintenance"],
                                   "CRITICAL": ["facilities", "maintenance", "plant_manager"], "gas": ["safety_officer"]},
            "channels": ["in-app"]}


class Tariffs(BaseModel):
    electricity: float = Field(ge=0, le=100)
    gas: float = Field(ge=0, le=100)
    water: float = Field(ge=0, le=1000)


@router.put("/settings/tariffs")
def set_tariffs(body: Tariffs):
    eng = get_engine()
    eng.tariffs.update(body.model_dump())
    eng._save_setting("tariffs", eng.tariffs)
    eng._kpi_cache = None
    return eng.tariffs


# ------------------------------------------------------------------ issues: what, where, who, how long, what to do
@router.get("/issues")
def issues(status: Literal["all", "open", "closed"] = "open", severity: str | None = None, zone: str | None = None,
           assignee: str | None = None, limit: int = Query(default=300, le=1000)):
    rows = iss.list_issues(get_engine(), status, severity, zone, assignee, limit)
    return {"count": len(rows), "issues": rows}


@router.get("/issues/summary")
def issues_summary():
    return iss.summary(get_engine())


@router.get("/issues/{alert_id}")
def issue(alert_id: int):
    d = iss.issue_detail(get_engine(), alert_id)
    if d is None:
        raise ActionError(f"Issue {alert_id} not found.")
    return d


@router.get("/overview")
def overview():
    """Status of every utility (live readings and open issues together) and the issues that need attention first."""
    return use.overview(get_engine())


@router.get("/usage")
def usage(utility: str = Query(..., description="e.g. COMPRESSED_AIR")):
    """Usage today against yesterday and the normal range, and the last 7 days (mock usage model that follows the issues)."""
    return use.usage(get_engine(), utility.upper())


@router.get("/agent/activity")
def agent_activity(days: int = Query(default=7, ge=1, le=30), limit: int = Query(default=40, ge=1, le=200)):
    """What the agent did: detections, hand-offs, escalations, clearings and verifications, with today's counts."""
    return aa.activity(get_engine(), days, limit)


@router.get("/people")
def people():
    return {"people": iss.roster(get_engine())}


# ------------------------------------------------------------------ mock data for the proof of concept
@router.post("/mock/seed")
def mock_seed():
    """Replace the mock roster and incident history. Simulated live alerts are not touched."""
    res = mock.seed()
    iss.clear_people_cache()
    get_engine().reload_from_db()
    return res


@router.delete("/mock")
def mock_clear():
    with SessionLocal() as s:
        res = mock.clear_mock(s)
        s.commit()
    iss.clear_people_cache()
    get_engine().reload_from_db()
    return res
