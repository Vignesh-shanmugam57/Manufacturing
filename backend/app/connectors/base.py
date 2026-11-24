from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal


class ConnectorError(ValueError):
    """A problem the person can fix (wrong password, unreachable host...). The message is shown as it is."""


@dataclass
class TestResult:
    ok: bool
    message: str
    tables: list[str] | None = None
    columns: list[str] = field(default_factory=list)
    sample: list[dict] = field(default_factory=list)
    ms: int = 0


@dataclass
class PullResult:
    rows: list[dict]
    cursor: dict | None = None
    message: str = ""
    raw_csv: bytes | None = None          # a CSV pulled as it is (already in a dataset's own format)


def jsonable(v):
    """A value that can be stored in JSON and turned into CSV text."""
    if isinstance(v, dt.datetime):
        return v.replace(tzinfo=None).isoformat()
    if isinstance(v, dt.date):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (bytes, bytearray, memoryview)):
        return bytes(v).hex()
    return v


class Adapter:
    """One kind of source. Both methods only read."""

    def test(self, cfg: dict, secrets: dict) -> TestResult:           # pragma: no cover - interface
        raise NotImplementedError

    def pull(self, cfg: dict, secrets: dict, cursor: dict | None, limit: int) -> PullResult:   # pragma: no cover
        raise NotImplementedError
