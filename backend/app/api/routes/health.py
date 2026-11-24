from fastapi import APIRouter

from app.core.config import settings
from app.db.session import ping

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    try:
        db_ok = ping()
    except Exception:  # noqa: BLE001 - report, don't fail the health check itself
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "database": "postgresql" if settings.is_postgres else "sqlite",
            "database_ok": db_ok, "model": settings.model_name, "site": settings.site_name}
