"""Who is on shift, and who should go to a problem.

The roster is a table (`twin_people`). A new alert is routed to a person by utility: the team that owns that utility,
then the utilities engineer, the shift supervisor and the plant manager as fallbacks. Only people who are on shift
at that moment and cover the zone are considered. Nothing here operates equipment; it only decides who is told.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.twin import TwinPerson

SHIFT_HOURS = {"A": "06:00 to 14:00", "B": "14:00 to 22:00", "C": "22:00 to 06:00", "ALL": "On call 24 h"}

# which team looks after which utility first
TEAM_FOR_UTILITY = {
    "COMPRESSED_AIR": "Maintenance team", "STEAM": "Maintenance team", "CHILLED_WATER": "Maintenance team",
    "COOLING_TOWER": "Maintenance team", "HVAC": "Facilities team", "WATER": "Facilities team", "GAS": "Safety officer",
}
FALLBACK_TEAMS = ["Utilities engineer", "Shift supervisor", "Plant manager"]


def shift_at(when: dt.datetime) -> str:
    h = when.hour
    return "A" if 6 <= h < 14 else "B" if 14 <= h < 22 else "C"


def person_dict(r: TwinPerson) -> dict:
    return {"id": r.id, "name": r.name, "role": r.role, "team": r.team, "shift": r.shift, "phone_ext": r.phone_ext,
            "zones": r.zones or [], "active": bool(r.active)}


def load_people(s: Session) -> list[dict]:
    return [person_dict(r) for r in s.scalars(select(TwinPerson).order_by(TwinPerson.id))]


def is_on_shift(p: dict, when: dt.datetime) -> bool:
    return bool(p["active"]) and (p["shift"] == "ALL" or p["shift"] == shift_at(when))


def covers(p: dict, zone: str | None) -> bool:
    z = p.get("zones") or []
    return "*" in z or zone is None or zone in z


def choose(people: list[dict], utility: str, zone: str | None, when: dt.datetime) -> dict | None:
    """The person who should go: on shift and in the right team. Within a team, someone who covers the zone comes first.
    If nobody in that team is on shift, the next team in the chain is tried (utilities engineer, supervisor, manager)."""
    on = [p for p in people if is_on_shift(p, when)]
    for team in [TEAM_FOR_UTILITY.get(utility, "Maintenance team"), *FALLBACK_TEAMS]:
        members = [p for p in on if p["team"] == team]
        local = [p for p in members if covers(p, zone)]
        if local or members:
            return (local or members)[0]
    return on[0] if on else None


def responder_for(s: Session, utility: str, zone: str | None, when: dt.datetime) -> dict | None:
    return choose(load_people(s), utility, zone, when)
