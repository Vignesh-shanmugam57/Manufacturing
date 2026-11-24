"""SQL sources: PostgreSQL, MySQL / MariaDB and SQL Server (and SQLite, used by the tests). Read only.

Every connection is opened as read-only where the database supports it, only one SELECT is ever sent, and a pull is
capped. Use a database account that can only read, so the database itself enforces what this code promises.
"""
from __future__ import annotations

import datetime as dt
import ssl
import time
from decimal import Decimal

from sqlalchemy import column, create_engine, inspect, literal_column, select, table, text
from sqlalchemy.engine import URL
from sqlalchemy.pool import NullPool

from app.connectors import safety
from app.connectors.base import Adapter, ConnectorError, PullResult, TestResult, jsonable

CONNECT_TIMEOUT = 10
SAMPLE_ROWS = 5
DEFAULT_PORT = {"postgresql": 5432, "mysql": 3306, "sqlserver": 1433}


def friendly(e: Exception) -> str:
    """A short, safe explanation of a connection problem (never includes the password)."""
    raw = str(e)
    low = raw.lower()
    if "password authentication failed" in low or "access denied" in low or "login failed" in low or "28p01" in low:
        return "The user name or password was not accepted."
    if "getaddrinfo" in low or "name or service not known" in low or "could not translate host" in low or "nodename nor servname" in low:
        return "The host name could not be found."
    if "refused" in low:
        return "The server refused the connection. Check the host and port, and that the server accepts connections from here."
    if "timed out" in low or "timeout" in low:
        return "The server did not answer in time. Check the host and port, and any firewall."
    if "does not exist" in low and "database" in low:
        return "That database does not exist on the server."
    if "no module named" in low:
        return "The driver for this database is not installed."
    return (raw.splitlines()[0] if raw else type(e).__name__)[:200]


def _cursor_value(cursor: dict):
    v, t = cursor.get("value"), cursor.get("type")
    if t == "datetime":
        return dt.datetime.fromisoformat(v)
    if t == "number":
        return float(v)
    return v


def _cursor_of(v) -> dict:
    t = "datetime" if isinstance(v, dt.datetime) else "number" if isinstance(v, (int, float, Decimal)) and not isinstance(v, bool) else "text"
    return {"value": jsonable(v), "type": t}


class SqlAdapter(Adapter):
    def __init__(self, kind: str):
        self.kind = kind

    # ------------------------------------------------------------------ connection
    def _engine(self, cfg: dict, secrets: dict):
        if self.kind == "sqlite":                                    # used by the tests
            return create_engine(URL.create("sqlite", database=cfg["database"]), poolclass=NullPool)
        host, db, user = (cfg.get("host") or "").strip(), (cfg.get("database") or "").strip(), (cfg.get("username") or "").strip()
        if not host or not db or not user:
            raise ConnectorError("Host, database and user name are required.")
        try:
            port = int(cfg.get("port") or DEFAULT_PORT[self.kind])
        except (TypeError, ValueError) as e:
            raise ConnectorError("The port must be a number.") from e
        password = secrets.get("password", "")
        mode = cfg.get("ssl", "require" if self.kind == "postgresql" else "off")
        args: dict = {}
        if self.kind == "postgresql":
            driver, args = "postgresql+pg8000", {"timeout": CONNECT_TIMEOUT}
            if mode in ("require", "verify"):
                ctx = ssl.create_default_context()
                if mode == "require":                                # encrypt without checking the certificate
                    ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
                args["ssl_context"] = ctx
        elif self.kind == "mysql":
            driver, args = "mysql+pymysql", {"connect_timeout": CONNECT_TIMEOUT, "read_timeout": 30}
            if mode in ("require", "verify"):
                args["ssl"] = {"check_hostname": mode == "verify"}
        elif self.kind == "sqlserver":
            driver, args = "mssql+pytds", {"login_timeout": CONNECT_TIMEOUT, "timeout": 30}
        else:
            raise ConnectorError("Unknown database type.")
        url = URL.create(driver, username=user, password=password, host=host, port=port, database=db)
        return create_engine(url, poolclass=NullPool, connect_args=args)

    def _read_only(self, conn) -> None:
        if self.kind == "postgresql":
            conn.execute(text("SET TRANSACTION READ ONLY"))
        elif self.kind == "mysql":
            conn.execute(text("SET SESSION TRANSACTION READ ONLY"))
        elif self.kind == "sqlite":
            conn.execute(text("PRAGMA query_only = ON"))

    # ------------------------------------------------------------------ what to read
    @staticmethod
    def _statement(src: dict, cursor: dict | None, limit: int):
        mode = (src or {}).get("mode")
        if mode == "table":
            name = safety.assert_identifier(src.get("table", ""), "table name")
            schema, _, tbl = name.rpartition(".")
            stmt = select(literal_column("*")).select_from(table(tbl, schema=schema or None))
        elif mode == "query":
            stmt = select(literal_column("*")).select_from(text(f"({safety.assert_select(src.get('query', ''))}) AS src"))
        else:
            raise ConnectorError("Choose a table to read, or enter a query.")
        if src.get("cursor_column"):
            cc = column(safety.assert_identifier(src["cursor_column"], "cursor column"))
            if cursor:
                stmt = stmt.where(cc > _cursor_value(cursor))
            stmt = stmt.order_by(cc)
        return stmt.limit(limit)

    # ------------------------------------------------------------------ the two operations
    def test(self, cfg: dict, secrets: dict) -> TestResult:
        t0 = time.monotonic()
        try:
            eng = self._engine(cfg, secrets)
            try:
                with eng.connect() as conn:
                    self._read_only(conn)
                    conn.execute(text("SELECT 1"))
                    tables = sorted(inspect(conn).get_table_names())[:300]
                    cols: list[str] = []
                    sample: list[dict] = []
                    src = cfg.get("source") or {}
                    if src.get("mode") in ("table", "query") and (src.get("table") or src.get("query")):
                        res = conn.execute(self._statement(src, None, SAMPLE_ROWS))
                        cols = list(res.keys())
                        sample = [{k: jsonable(v) for k, v in zip(cols, r)} for r in res.fetchall()]
            finally:
                eng.dispose()
        except ConnectorError as e:
            return TestResult(False, str(e))
        except ValueError as e:
            return TestResult(False, str(e))
        except Exception as e:                                       # noqa: BLE001 - shown to the person, without secrets
            return TestResult(False, f"Could not connect. {friendly(e)}")
        ms = int((time.monotonic() - t0) * 1000)
        return TestResult(True, f"Connected in {ms / 1000:.1f} s. Found {len(tables)} table{'s' if len(tables) != 1 else ''}. "
                                "Reading is allowed; this app never writes.", tables, cols, sample, ms)

    def pull(self, cfg: dict, secrets: dict, cursor: dict | None, limit: int) -> PullResult:
        eng = self._engine(cfg, secrets)
        src = cfg.get("source") or {}
        try:
            with eng.connect() as conn:
                self._read_only(conn)
                res = conn.execute(self._statement(src, cursor, limit))
                cols = list(res.keys())
                raw = res.fetchall()
        except (ConnectorError, ValueError):
            raise
        except Exception as e:                                       # noqa: BLE001
            raise ConnectorError(f"Reading failed. {friendly(e)}") from e
        finally:
            eng.dispose()
        rows = [{k: jsonable(v) for k, v in zip(cols, r)} for r in raw]
        new_cursor = cursor
        cc = src.get("cursor_column")
        if cc and raw and cc in cols:
            new_cursor = _cursor_of(raw[-1][cols.index(cc)])
        return PullResult(rows, new_cursor, f"Read {len(rows)} row{'s' if len(rows) != 1 else ''}"
                          + (" (the most that is read per pull; the next pull continues)" if len(rows) >= limit else "") + ".")
