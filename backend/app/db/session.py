"""Database engines and sessions (Neon PostgreSQL in production, SQLite for local dev/tests)."""
from __future__ import annotations

import ssl
from collections.abc import Iterator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import DATA_DIR, settings


def pg_connect_options(url: str | URL) -> tuple[URL, dict]:
    """Driver-specific connection options for PostgreSQL / Neon.

    psycopg understands libpq params (sslmode, channel_binding). pg8000 does not, so they are translated
    into an SSL context: Neon hosts always get full certificate verification; elsewhere sslmode=require
    keeps libpq's meaning (encrypt, don't verify) and verify-ca / verify-full verify.
    """
    u = make_url(url)
    if u.drivername.endswith("+pg8000"):
        query = dict(u.query)
        sslmode = query.pop("sslmode", None)
        for libpq_only in ("channel_binding", "options", "target_session_attrs"):
            query.pop(libpq_only, None)
        u = u.set(query=query)
        args: dict = {}
        if (u.host or "").endswith(".neon.tech") or sslmode in ("verify-ca", "verify-full"):
            args["ssl_context"] = ssl.create_default_context()
        elif sslmode in ("require", "prefer", "allow"):
            ctx = ssl.create_default_context()
            ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
            args["ssl_context"] = ctx
        return u, args
    # psycopg: no server-side prepared statements (Neon's PgBouncer pooler runs in transaction mode)
    return u, {"prepare_threshold": None}


def make_engine(url: str, readonly: bool = False):
    if url.startswith("sqlite"):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        engine = create_engine(url, pool_pre_ping=True,
                               connect_args={"check_same_thread": False, "timeout": 30})

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            # query_only makes the SQL tool's connection unable to write (DB-level guard).
            cur.execute("PRAGMA query_only=ON" if readonly else "PRAGMA journal_mode=WAL")
            cur.close()
        return engine

    # PostgreSQL / Neon. Neon's pooled endpoint runs PgBouncer in transaction mode, so:
    #  - no server-side prepared statements, no session-level SETs (the SQL tool sets READ ONLY per transaction)
    #  - recycle connections because Neon computes scale to zero when idle
    u, connect_args = pg_connect_options(url)
    return create_engine(u, pool_pre_ping=True, pool_recycle=300, pool_size=5, max_overflow=5,
                         connect_args=connect_args)


engine = make_engine(settings.database_url)
ro_engine = make_engine(settings.readonly_database_url or settings.database_url, readonly=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


# Tables of the earlier demo-plant version (generated data). Replaced by the uploaded CSV tables.
_LEGACY_TABLES = ("tag_readings", "equipment_alarms", "maintenance_items", "utility_tags", "production_output",
                  "utility_assets")


def drop_legacy_tables() -> list[str]:
    """Remove the old demo-plant tables so the CSV-based schema can be created. Returns what was dropped."""
    insp = inspect(engine)
    names = set(insp.get_table_names())
    dropped = [t for t in _LEGACY_TABLES if t in names]
    # Same table names, old layout: recognise them by a column the new layout does not have.
    if "downtime_events" in names and "downtime_id" not in {c["name"] for c in insp.get_columns("downtime_events")}:
        dropped.append("downtime_events")
    if "utility_alerts" in names and "utility_type" not in {c["name"] for c in insp.get_columns("utility_alerts")}:
        dropped.append("utility_alerts")
    if dropped:
        with engine.begin() as conn:
            for t in dropped:
                conn.execute(text(f'DROP TABLE IF EXISTS "{t}"' + (" CASCADE" if engine.dialect.name == "postgresql" else "")))
    return dropped


def init_db() -> list[str]:
    """Create the tables. Returns the legacy demo tables that were dropped (usually none)."""
    from app.models import Base  # noqa: F401 - registers all models
    dropped = drop_legacy_tables()
    Base.metadata.create_all(engine)
    return dropped


def get_db() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


def ping() -> bool:
    with engine.connect() as conn:
        return conn.scalar(text("SELECT 1")) == 1


def ensure_database(url: str | None = None) -> str:
    """Create the target PostgreSQL database (e.g. `utilities` on Neon) if it does not exist."""
    u, connect_args = pg_connect_options(url or settings.database_url)
    if not u.drivername.startswith("postgresql"):
        return "not PostgreSQL - nothing to create"
    target = u.database
    last_error: Exception | None = None
    for admin_db in ("neondb", "postgres"):
        admin = create_engine(u.set(database=admin_db), isolation_level="AUTOCOMMIT", connect_args=connect_args)
        try:
            with admin.connect() as conn:
                if conn.scalar(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": target}):
                    return f"database '{target}' already exists"
                conn.execute(text(f'CREATE DATABASE "{target}"'))
                return f"database '{target}' created"
        except DBAPIError as e:
            last_error = e
        finally:
            admin.dispose()
    raise RuntimeError(f"Could not connect to an admin database to create '{target}': {last_error}")
