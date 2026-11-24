"""LangChain tools for the Utilities Management Agent.

Every tool is read-only. The agent cannot raise, assign or close issues, and there is deliberately NO tool that
changes setpoints or actuates valves, pumps, compressors, boilers, chillers or fans: the monitoring raises issues,
people act on them on the Issues page, and control and emergency/safety actions stay with certified operators.
"""
from __future__ import annotations

import datetime as dt
import json
import re

from langchain_core.tools import tool
from sqlalchemy import inspect, text

from app.agent import plant_tools
from app.db.session import SessionLocal, ro_engine
from app.services import analytics as an


def _default(o):
    if isinstance(o, dt.datetime):
        return o.strftime("%Y-%m-%d %H:%M")
    if isinstance(o, dt.date):
        return o.isoformat()
    return str(o)


def to_json(obj) -> str:
    return json.dumps(obj, default=_default, separators=(",", ":"))


# ------------------------------------------------------------------ analysis (read-only)
@tool
def get_data_overview() -> str:
    """What data is loaded (rows and date range of the utility, machine and downtime files), the plants, utility
    types, zones, and data-quality warnings (mixed units, sparse sampling, alarm/sensor problems).
    Call this first when unsure what data exists, or when other tools say no data was uploaded."""
    with SessionLocal() as s:
        return to_json(an.data_overview(s))


@tool
def get_utility_health_board() -> str:
    """Status of every utility (NORMAL/WATCH/ALARM) with reasons, last-24h readings vs the previous 7 days, alarm
    counts, top abnormal patterns, the downtime-link verdict and top efficiency recommendations.
    Start here for 'how are the utilities / what is the status' questions."""
    with SessionLocal() as s:
        return to_json(an.health_board(s))


@tool
def get_consumption_trends(utility_type: str = "", plant_id: str = "", zone: str = "", period: str = "week",
                           periods: int = 8, group_by: str = "utility_type") -> str:
    """Consumption (flow_rate), pressure and temperature trend per day or week, with last-vs-previous change and
    direction. utility_type e.g. COMPRESSED_AIR, CHILLED_WATER, HVAC, PROCESS_WATER, NITROGEN (empty = all);
    plant_id e.g. IN-TN-01; zone e.g. SMT, ASSEMBLY, TEST, WAREHOUSE; period: day or week;
    group_by: utility_type, plant or zone."""
    with SessionLocal() as s:
        return to_json(an.consumption_trends(s, utility_type or None, plant_id or None, zone or None, period,
                                             periods, group_by))


@tool
def detect_abnormal_usage(days: int = 7, utility_type: str = "", plant_id: str = "", zone: str = "") -> str:
    """Abnormal consumption: compares the last `days` of every utility/plant/zone series with its own earlier
    history (flow, pressure, temperature level shifts) and finds alarm clusters. Returns findings with evidence
    (recent vs baseline, change %, z-score), likely cause and recommended action, plus alarm counts and a conclusion.
    Says explicitly when nothing abnormal is found."""
    with SessionLocal() as s:
        return to_json(an.detect_abnormal_usage(s, days, utility_type or None, plant_id or None, zone or None))


@tool
def get_downtime_correlation(utility_type: str = "", plant_id: str = "", window_hours: int = 2, days: int = 0) -> str:
    """Utility vs downtime: do downtime events start more often within `window_hours` after a utility alarm at the
    same plant? Returns lift and z-score per utility type, machine DOWN share, a downtime summary (events, minutes,
    by reason and line, open events) and a conclusion. days=0 means all data."""
    with SessionLocal() as s:
        return to_json(an.downtime_correlation(s, utility_type or None, plant_id or None, window_hours, days or None))


@tool
def get_efficiency_recommendations() -> str:
    """Efficiency opportunities: whether utility demand falls when machines are idle/down, night vs day load, zones
    using more than their peers, and equipment with unusually many alarms. Returns prioritized recommendations
    with owners, plus a caveat on how the estimates were made."""
    with SessionLocal() as s:
        return to_json(an.efficiency_opportunities(s))


# ------------------------------------------------------------------ ad-hoc SQL (setup guide 6.5)
FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|truncate|create|grant|revoke|copy|call|do|merge|attach|detach|pragma|"
    r"vacuum|reindex|set_config|dblink\w*|lo_\w+)\b|\bpg_\w+\s*\(", re.I)
# Users and chat history are never exposed to the model.
HIDDEN_TABLES = {"users", "chat_sessions", "chat_messages", "data_uploads"}


@tool
def get_schema() -> str:
    """List the data tables (utility_readings, machine_readings, downtime_events, utility_alerts) and their columns, for writing ad-hoc SQL with run_sql."""
    insp = inspect(ro_engine)
    return "\n".join(
        f"{t}({', '.join(c['name'] + ':' + str(c['type']) for c in insp.get_columns(t))})"
        for t in insp.get_table_names() if t not in HIDDEN_TABLES)


@tool
def run_sql(query: str) -> str:
    """Run ONE read-only SELECT on the plant data and return up to 50 rows. Call get_schema first.
    Prefer the dedicated tools; use this only for questions they cannot answer."""
    q = query.strip().rstrip(";")
    if ";" in q or not re.match(r"^(select|with)\b", q, re.I) or FORBIDDEN.search(q):
        return "ERROR: only a single read-only SELECT is allowed."
    if any(re.search(rf"\b{t}\b", q, re.I) for t in HIDDEN_TABLES):
        return "ERROR: user and chat tables are not queryable."
    try:
        with ro_engine.connect() as conn:
            if conn.dialect.name == "postgresql":
                # Transaction-scoped, so it also works through Neon's PgBouncer pooler.
                conn.execute(text("SET TRANSACTION READ ONLY"))
                conn.execute(text("SET LOCAL statement_timeout = 8000"))
            res = conn.execute(text(f"SELECT * FROM ({q}) AS t LIMIT 50"))
            cols = list(res.keys())
            rows = [dict(zip(cols, r)) for r in res.fetchall()]
            return to_json(rows) if rows else "No rows."
    except Exception as e:  # noqa: BLE001 - errors go back to the model
        return f"ERROR: {e}"


TOOLS = [get_data_overview, get_utility_health_board, get_consumption_trends, detect_abnormal_usage,
         get_downtime_correlation, get_efficiency_recommendations, get_schema, run_sql, *plant_tools.PLANT_TOOLS]
