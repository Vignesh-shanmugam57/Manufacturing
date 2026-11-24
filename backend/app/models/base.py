import datetime as dt

from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase

# JSONB on PostgreSQL (Neon), plain JSON elsewhere. Python None is stored as SQL NULL (not JSON 'null'),
# so "steps IS NULL" means "no tool trace".
JSONType = JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql")


def utcnow_naive() -> dt.datetime:
    """Plant-local naive timestamps, consistent with the telemetry tables."""
    return dt.datetime.now().replace(microsecond=0)


class Base(DeclarativeBase):
    pass
