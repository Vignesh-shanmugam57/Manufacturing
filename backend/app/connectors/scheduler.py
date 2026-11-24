"""Pulls from connected systems on their schedule.

The schedule is kept in memory: the database is read once at start and again only when a connection is created, changed
or removed. The loop itself never queries the database, so an idle app lets a serverless database (Neon) go to sleep.
It assumes one server process, like the telemetry engine.
"""
from __future__ import annotations

import datetime as dt
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select

from app.connectors import service
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.connectors import DataConnector

log = logging.getLogger("connectors")
CHECK_EVERY_S = 10
_stop = threading.Event()
_thread: threading.Thread | None = None
_pool: ThreadPoolExecutor | None = None
_sched: dict[int, tuple[int, dt.datetime | None]] = {}          # connection id -> (every N seconds, last pulled)
_lock = threading.Lock()


def refresh() -> None:
    """Reload which connections are scheduled (one query)."""
    try:
        with SessionLocal() as s:
            rows = s.execute(select(DataConnector.id, DataConnector.schedule_s, DataConnector.last_run_at)
                             .where(DataConnector.enabled.is_(True), DataConnector.schedule_s > 0)).all()
    except Exception:                                              # noqa: BLE001 - keep the old schedule and try again on the next change
        log.exception("could not read the connector schedule")
        return
    with _lock:
        _sched.clear()
        _sched.update({i: (every, last) for i, every, last in rows})


def refresh_async() -> None:
    """Call after a connection is created, changed or removed. Does nothing when scheduled pulls are switched off."""
    if settings.connectors_autorun:
        threading.Thread(target=refresh, name="connector-refresh", daemon=True).start()


def _due() -> list[int]:
    now = dt.datetime.now()
    with _lock:
        return [i for i, (every, last) in _sched.items() if last is None or (now - last).total_seconds() >= every]


def _pull(connector_id: int) -> None:
    try:
        service.run(connector_id, "schedule")
    except Exception:                                              # noqa: BLE001 - a failed pull is recorded; the loop goes on
        log.exception("scheduled pull %s failed", connector_id)


def _loop() -> None:
    refresh()
    while not _stop.wait(CHECK_EVERY_S):
        try:
            for cid in _due():
                with _lock:
                    if cid in _sched:
                        _sched[cid] = (_sched[cid][0], dt.datetime.now())      # not due again until the interval has passed
                if _pool is not None:
                    _pool.submit(_pull, cid)
        except Exception:                                          # noqa: BLE001
            log.exception("connector scheduler")


def start() -> None:
    global _thread, _pool
    if not settings.connectors_autorun or (_thread and _thread.is_alive()):
        return
    _stop.clear()
    _pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="connector")
    _thread = threading.Thread(target=_loop, name="connector-scheduler", daemon=True)
    _thread.start()


def stop() -> None:
    _stop.set()
    if _pool is not None:
        _pool.shutdown(wait=False, cancel_futures=True)
