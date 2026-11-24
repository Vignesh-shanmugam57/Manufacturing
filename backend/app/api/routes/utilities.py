"""Deterministic utility views for the dashboard (no LLM involved)."""
from fastapi import APIRouter, Depends

from app.api.deps import DbSession, get_current_user
from app.services import alerts as al
from app.services import analytics as an
from app.services import monitor

router = APIRouter(prefix="/utilities", tags=["utilities"], dependencies=[Depends(get_current_user)])


@router.get("/health-board")
def health_board(db: DbSession):
    board = an.health_board(db)
    board["open_alerts"] = al.list_alerts(db, "open")["count"]
    return board


@router.get("/overview")
def overview(db: DbSession):
    return an.data_overview(db)


@router.get("/trends")
def trends(db: DbSession, utility_type: str | None = None, plant_id: str | None = None, zone: str | None = None,
           period: str = "week", periods: int = 8, group_by: str = "utility_type"):
    return an.consumption_trends(db, utility_type, plant_id, zone, period, periods, group_by)


@router.get("/anomalies")
def anomalies(db: DbSession, days: int = 7, utility_type: str | None = None, plant_id: str | None = None,
              zone: str | None = None):
    return an.detect_abnormal_usage(db, days, utility_type, plant_id, zone)


@router.get("/downtime-correlation")
def downtime_correlation(db: DbSession, utility_type: str | None = None, plant_id: str | None = None,
                         window_hours: int = 2, days: int | None = None):
    return an.downtime_correlation(db, utility_type, plant_id, window_hours, days)


@router.get("/efficiency")
def efficiency(db: DbSession):
    return an.efficiency_opportunities(db)


@router.post("/scan")
def scan(db: DbSession):
    """Run the monitoring scan and raise de-duplicated advisory alerts."""
    return monitor.run_scan(db)
