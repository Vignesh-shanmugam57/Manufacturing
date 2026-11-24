"""A sample data source served by this app itself, so a REST or CSV connection can be shown working without any outside
system. It holds synthetic hourly utility readings only, needs no sign-in, and changes nothing."""
import csv
import datetime as dt
import io

from fastapi import APIRouter, Response

from app.connectors import demo

router = APIRouter(prefix="/demo", tags=["demo source"])


def _rows(hours: int = 24) -> list[dict]:
    now = dt.datetime.now()
    return demo.rows_between(now - dt.timedelta(hours=hours - 1), now)


@router.get("/utility.json")
def utility_json():
    """Hourly utility readings of the last 24 hours as JSON: {"data": {"rows": [...]}}."""
    return {"data": {"rows": _rows()}}


@router.get("/utility.csv")
def utility_csv():
    """The same readings as a CSV in the format of the Utility telemetry dataset."""
    out = io.StringIO(newline="")
    w = csv.DictWriter(out, fieldnames=demo.COLUMNS)
    w.writeheader()
    w.writerows(_rows())
    return Response(out.getvalue(), media_type="text/csv")
