"""Connections to the plant's data applications: what can be connected, test a connection, save it, pull from it.

Read only: the app never writes to a source. Passwords and tokens are stored encrypted and are never returned.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, get_current_user
from app.connectors import registry, scheduler, service
from app.models.connectors import DataConnector
from app.services import ingest
from app.services.errors import NotFoundError

router = APIRouter(prefix="/connectors", tags=["connectors"], dependencies=[Depends(get_current_user)])


def _actor(user) -> str:
    return f"{user.name} ({user.role or 'user'})"


def _get(db, connector_id: int) -> DataConnector:
    c = db.get(DataConnector, connector_id)
    if c is None:
        raise NotFoundError(f"Connection {connector_id} not found.")
    return c


@router.get("/catalog")
def catalog():
    """Every connection type with the form it needs, where data can go, and the schedules on offer."""
    targets = [{"key": service.LIVE_FEED, "label": "Live plant feed", "fields": service.target_fields(service.LIVE_FEED),
                "purpose": "Sensor readings shown live on the map. Needs the live feed switched to live."}]
    targets += [{"key": k, "label": d.label, "fields": list(d.columns), "purpose": d.purpose} for k, d in ingest.DATASETS.items()]
    return {"kinds": registry.catalog(), "categories": registry.CATEGORIES, "targets": targets,
            "schedules": [{"seconds": s, "label": label} for s, label in service.SCHEDULES.items()]}


class TestBody(BaseModel):
    kind: str
    config: dict = Field(default_factory=dict)
    secrets: dict = Field(default_factory=dict)
    source: dict | None = None            # for databases: {"mode": "table", "table": "...", "cursor_column": "..."} or {"mode": "query", "query": "..."}


@router.post("/test")
def test(body: TestBody):
    """Try the connection and read a few rows. Nothing is saved."""
    return service.test_connection(body.kind, body.config, body.secrets, body.source)


class SuggestBody(BaseModel):
    target: str
    columns: list[str]


@router.post("/suggest-mapping")
def suggest(body: SuggestBody):
    return service.suggest_mapping(body.target, body.columns)


@router.get("")
def list_connectors(db: DbSession):
    rows = db.scalars(select(DataConnector).order_by(DataConnector.id)).all()
    return {"connectors": [service.connector_dict(c) for c in rows]}


class CreateBody(BaseModel):
    name: str | None = None
    kind: str
    config: dict = Field(default_factory=dict)
    secrets: dict = Field(default_factory=dict)
    source: dict | None = None
    target: str
    mapping: dict | None = None
    columns: list[str] | None = None       # the source's columns, used to match fields by name when no mapping is given
    schedule_s: int = 0
    run_now: bool = True


@router.post("")
def create(body: CreateBody, db: DbSession, user: CurrentUser):
    c = service.create(db, body.model_dump(exclude={"run_now"}), _actor(user))
    out = {"connector": service.connector_dict(c), "run": None}
    if body.run_now:
        out["run"] = service.run(c.id, "create")
        out["connector"] = out["run"]["connector"]
    scheduler.refresh_async()
    return out


class UpdateBody(BaseModel):
    name: str | None = None
    enabled: bool | None = None
    schedule_s: int | None = None
    target: str | None = None
    mapping: dict | None = None
    config: dict | None = None
    secrets: dict | None = None
    reset_cursor: bool | None = None


@router.patch("/{connector_id}")
def update(connector_id: int, body: UpdateBody, db: DbSession):
    c = service.update(db, _get(db, connector_id), body.model_dump(exclude_none=True))
    scheduler.refresh_async()
    return service.connector_dict(c)


@router.delete("/{connector_id}")
def delete(connector_id: int, db: DbSession):
    service.delete_connector(db, _get(db, connector_id))
    scheduler.refresh_async()
    return {"deleted": connector_id}


@router.post("/{connector_id}/pull")
def pull(connector_id: int, db: DbSession):
    """Pull now. Reads only; rows that are already stored are skipped."""
    _get(db, connector_id)
    return service.run(connector_id, "manual")


@router.get("/{connector_id}/runs")
def runs(connector_id: int, db: DbSession):
    _get(db, connector_id)
    return {"runs": service.runs(db, connector_id)}
