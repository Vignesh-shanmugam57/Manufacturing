"""Alert workflow: OPEN -> ACKNOWLEDGED -> RESOLVED (people) -> VERIFIED (telemetry check)."""
from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession
from app.schemas.alerts import AlertAssignIn, AlertCreate, AlertStatusIn
from app.services import alerts as al

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("")
def list_alerts(user: CurrentUser, db: DbSession, status: str = "open", utility_type: str | None = None):
    return al.list_alerts(db, status, utility_type)


@router.post("", status_code=201)
def create_alert(body: AlertCreate, user: CurrentUser, db: DbSession):
    """Raise an advisory alert by hand. An identical open alert is returned instead of creating a duplicate."""
    alert, created = al.create_alert(db, utility_type=body.utility_type, title=body.title, severity=body.severity,
                                     recommendation=body.recommendation, details=body.details, plant_id=body.plant_id,
                                     zone=body.zone, assigned_to=body.assigned_to, category="manual", source="user")
    return {"created": created, "alert": al.alert_dict(alert)}


@router.post("/{alert_id}/status")
def set_status(alert_id: int, body: AlertStatusIn, user: CurrentUser, db: DbSession):
    return al.update_alert_status(db, alert_id, body.status, body.note, by=f"{user.name} <{user.email}>")


@router.post("/{alert_id}/assign")
def assign(alert_id: int, body: AlertAssignIn, user: CurrentUser, db: DbSession):
    """Give an alert to a team or person. The change is recorded with who made it."""
    return al.assign_alert(db, alert_id, body.assignee, by=f"{user.name} <{user.email}>")


@router.post("/{alert_id}/verify")
def verify(alert_id: int, user: CurrentUser, db: DbSession, hours: int = 48):
    return al.verify_return_to_normal(db, alert_id, hours)
