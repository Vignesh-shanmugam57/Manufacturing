"""Guards: SQL may only read, and web connectors may not be pointed at cloud metadata or other unsafe addresses."""
from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urlparse

from app.core.config import settings

BLOCKED_NETWORKS = [ipaddress.ip_network(n) for n in ("169.254.0.0/16", "0.0.0.0/8", "224.0.0.0/4", "fe80::/10")]


def check_url(url: str) -> str:
    """http or https only, no link-local or metadata addresses, and the optional host allow-list. Returns the URL."""
    u = urlparse((url or "").strip())
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ValueError("Enter a web address that starts with http:// or https://.")
    allowed = [h.strip().lower() for h in settings.connector_allowed_hosts.split(",") if h.strip()]
    if allowed and u.hostname.lower() not in allowed:
        raise ValueError(f"{u.hostname} is not in the list of hosts this app may call (CONNECTOR_ALLOWED_HOSTS).")
    try:
        infos = socket.getaddrinfo(u.hostname, u.port or (443 if u.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise ValueError(f"The host {u.hostname} could not be found.") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if any(ip in net for net in BLOCKED_NETWORKS):
            raise ValueError("That address is not allowed (link-local and cloud metadata addresses are blocked).")
    return u.geturl()


_FORBIDDEN = re.compile(r"\b(insert|update|delete|drop|alter|create|truncate|merge|exec|execute|grant|revoke|call|copy|vacuum|attach|pragma|into|replace)\b", re.I)
IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*(\.[A-Za-z_][A-Za-z0-9_$]*)?$")


def assert_select(sql: str) -> str:
    """One SELECT (or WITH ... SELECT) statement and nothing else."""
    s = (sql or "").strip().rstrip(";").strip()
    if not s:
        raise ValueError("Enter a query.")
    bare = re.sub(r"'(?:[^']|'')*'", "''", s)
    bare = re.sub(r'"(?:[^"]|"")*"', '""', bare)
    bare = re.sub(r"--[^\n]*|/\*.*?\*/", " ", bare, flags=re.S)
    if ";" in bare:
        raise ValueError("Only one statement is allowed.")
    if not re.match(r"^\s*(select|with)\b", bare, re.I):
        raise ValueError("Only SELECT queries are allowed. This app reads data and never changes it.")
    bad = _FORBIDDEN.search(bare)
    if bad:
        raise ValueError(f"'{bad.group(1)}' is not allowed. This app reads data and never changes it.")
    return s


def assert_identifier(name: str, what: str = "name") -> str:
    if not name or not IDENT.match(name.strip()):
        raise ValueError(f"The {what} may only contain letters, numbers and underscores (and one dot for schema.table).")
    return name.strip()
