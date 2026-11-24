"""Web sources: a REST API that answers with JSON, and a CSV file at a web address. GET only."""
from __future__ import annotations

import csv
import io
import json
import time

import httpx

from app.connectors import safety
from app.connectors.base import Adapter, ConnectorError, PullResult, TestResult, jsonable

MAX_BYTES = 20 * 1024 * 1024
TIMEOUT_S = 20.0
SAMPLE_ROWS = 5
MAX_JSON_ROWS = 20000
MAX_CSV_ROWS = 100000


def _client() -> httpx.Client:                                       # the tests replace this with a mock transport
    return httpx.Client(timeout=TIMEOUT_S, follow_redirects=False)


def _request_parts(cfg: dict, secrets: dict) -> tuple[dict, tuple | None]:
    headers = {"Accept": cfg.get("accept", "*/*"), "User-Agent": "utilities-agent-connector"}
    auth = None
    mode = cfg.get("auth", "none")
    if mode == "bearer":
        headers["Authorization"] = f"Bearer {secrets.get('token', '')}"
    elif mode == "header":
        if not cfg.get("header_name"):
            raise ConnectorError("Enter the name of the header that carries the key.")
        headers[cfg["header_name"]] = secrets.get("token", "")
    elif mode == "basic":
        auth = (cfg.get("username", ""), secrets.get("password", ""))
    return headers, auth


def fetch(cfg: dict, secrets: dict) -> bytes:
    url = safety.check_url(cfg.get("url", ""))
    headers, auth = _request_parts(cfg, secrets)
    try:
        with _client() as c, c.stream("GET", url, headers=headers, auth=auth) as r:
            if 300 <= r.status_code < 400:
                raise ConnectorError(f"The address redirects to {r.headers.get('location', 'another address')}. Use that address instead.")
            if r.status_code in (401, 403):
                raise ConnectorError(f"The server did not accept the sign-in ({r.status_code}). Check the key or password.")
            if r.status_code >= 400:
                raise ConnectorError(f"The server answered {r.status_code}.")
            data = bytearray()
            for chunk in r.iter_bytes():
                data += chunk
                if len(data) > MAX_BYTES:
                    raise ConnectorError(f"The answer is larger than {MAX_BYTES // (1024 * 1024)} MB, which is the most this app reads in one pull.")
            return bytes(data)
    except httpx.TimeoutException as e:
        raise ConnectorError("The server did not answer in time.") from e
    except httpx.ConnectError as e:
        raise ConnectorError("Could not reach the server. Check the address and any firewall.") from e
    except httpx.HTTPError as e:
        raise ConnectorError(f"The request failed: {type(e).__name__}.") from e


def _flatten(d: dict, prefix: str = "") -> dict:
    out = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flatten(v, key + "."))
        else:
            out[key] = jsonable(v)
    return out


def _columns(rows: list[dict]) -> list[str]:
    cols: list[str] = []
    for r in rows[:50]:
        for k in r:
            if k not in cols:
                cols.append(k)
    return cols


class RestJsonAdapter(Adapter):
    @staticmethod
    def rows(content: bytes, rows_path: str | None) -> list[dict]:
        try:
            data = json.loads(content.decode("utf-8-sig"))
        except (ValueError, UnicodeDecodeError) as e:
            raise ConnectorError("The server did not answer with JSON.") from e
        for part in [p for p in (rows_path or "").split(".") if p]:
            if isinstance(data, dict) and part in data:
                data = data[part]
            else:
                raise ConnectorError(f"'{rows_path}' was not found in the answer. Check where the rows are.")
        if isinstance(data, dict):                                   # no path given: use the first list of records
            lists = [v for v in data.values() if isinstance(v, list) and v and isinstance(v[0], dict)]
            data = lists[0] if lists else [data]
        if not isinstance(data, list) or not all(isinstance(x, dict) for x in data):
            raise ConnectorError("The answer is not a list of records. Set 'Where the rows are' to the right place in the answer.")
        return [_flatten(x) for x in data[:MAX_JSON_ROWS]]

    def test(self, cfg: dict, secrets: dict) -> TestResult:
        t0 = time.monotonic()
        try:
            rows = self.rows(fetch(cfg, secrets), cfg.get("rows_path"))
        except ValueError as e:
            return TestResult(False, str(e))
        ms = int((time.monotonic() - t0) * 1000)
        cols = _columns(rows)
        return TestResult(True, f"Connected in {ms / 1000:.1f} s. The answer holds {len(rows):,} record{'s' if len(rows) != 1 else ''} "
                                f"with {len(cols)} fields.", None, cols, rows[:SAMPLE_ROWS], ms)

    def pull(self, cfg: dict, secrets: dict, cursor: dict | None, limit: int) -> PullResult:
        rows = self.rows(fetch(cfg, secrets), cfg.get("rows_path"))[:limit]
        return PullResult(rows, cursor, f"Read {len(rows):,} record{'s' if len(rows) != 1 else ''}.")


class CsvUrlAdapter(Adapter):
    @staticmethod
    def parse(content: bytes) -> tuple[list[str], list[dict]]:
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as e:
            raise ConnectorError("The file is not UTF-8 text. Export it as a CSV (UTF-8).") from e
        if not text.strip():
            raise ConnectorError("The file is empty.")
        reader = csv.DictReader(io.StringIO(text, newline=""))
        header = [h.strip() for h in (reader.fieldnames or [])]
        reader.fieldnames = header
        rows = []
        for i, r in enumerate(reader):
            if i >= MAX_CSV_ROWS:
                break
            rows.append({k: v for k, v in r.items() if k is not None})
        return header, rows

    def test(self, cfg: dict, secrets: dict) -> TestResult:
        t0 = time.monotonic()
        try:
            header, rows = self.parse(fetch(cfg, secrets))
        except ValueError as e:
            return TestResult(False, str(e))
        ms = int((time.monotonic() - t0) * 1000)
        return TestResult(True, f"Connected in {ms / 1000:.1f} s. The file has {len(rows):,} row{'s' if len(rows) != 1 else ''} "
                                f"and {len(header)} columns.", None, header, rows[:SAMPLE_ROWS], ms)

    def pull(self, cfg: dict, secrets: dict, cursor: dict | None, limit: int) -> PullResult:
        content = fetch(cfg, secrets)
        _, rows = self.parse(content)
        return PullResult(rows[:limit], cursor, f"Read {len(rows):,} row{'s' if len(rows) != 1 else ''}.", raw_csv=content)
