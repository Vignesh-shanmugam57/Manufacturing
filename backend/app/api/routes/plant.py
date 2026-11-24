"""Plant operations: energy and cost, production and downtime, maintenance, quality, utilities and the issue workflow.

Every number is read from the database (Neon). Nothing is read from the CSV files at runtime. A single day can be
chosen from the last seven days of data; the figures then cover only that day.
"""
from fastapi import APIRouter, Depends, Query

from app.api.deps import DbSession, get_current_user
from app.services import operations

router = APIRouter(prefix="/plant", tags=["plant"], dependencies=[Depends(get_current_user)])


@router.get("/summary")
def summary(db: DbSession,
            days: int = Query(30, ge=1, le=120, description="window in days, counted back from the latest reading"),
            day: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$",
                                    description="one calendar day in the last seven days of data (YYYY-MM-DD)")):
    return operations.plant_summary(db, days, day)
