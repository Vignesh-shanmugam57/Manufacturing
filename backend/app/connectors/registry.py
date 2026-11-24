"""The connector types the app knows about, the form each one needs, and whether a working adapter exists for it.

`available` means a working adapter is installed. `verified` means it has been run against a real or mocked server in this
project. Types without an adapter keep their form, so the connection details can be collected; testing them says honestly
that the driver is added per project.
"""
from __future__ import annotations

from app.connectors.base import Adapter
from app.connectors.demo import DemoGateway
from app.connectors.sql import SqlAdapter
from app.connectors.web import CsvUrlAdapter, RestJsonAdapter


def F(key: str, label: str, type: str = "text", required: bool = True, secret: bool = False, default=None,
      options: list[str] | None = None, help: str = "", placeholder: str = "") -> dict:
    return {"key": key, "label": label, "type": type, "required": required, "secret": secret, "default": default,
            "options": options, "help": help, "placeholder": placeholder}


_DB_COMMON = [F("host", "Host", placeholder="db.plant.local"), F("port", "Port", "number"), F("database", "Database"),
              F("username", "Read-only user", help="Use an account that can only read."), F("password", "Password", "password", secret=True)]
_WEB_AUTH = [F("auth", "Sign in", "select", required=False, default="none", options=["none", "bearer", "header", "basic"],
               help="none, a bearer token, a key in a header, or a user name and password"),
             F("header_name", "Header name", required=False, help="Only for 'header', for example X-API-Key"),
             F("token", "Token or key", "password", required=False, secret=True),
             F("username", "User name", required=False, help="Only for 'basic'"),
             F("password", "Password", "password", required=False, secret=True)]

NOTE_DRIVER = "The connection form is ready. The driver for this system is added per project, once there is a server to connect to."

KINDS: dict[str, dict] = {
    "opcua": dict(label="OPC UA", category="Plant systems", icon="plug", blurb="SCADA, BMS and PLC servers", adapter=None,
                  fields=[F("server", "Server", placeholder="opc.tcp://scada01:4840"), F("security", "Security", "select", required=False, default="Sign and encrypt",
                          options=["None", "Sign", "Sign and encrypt"]), F("username", "User name", required=False), F("password", "Password", "password", required=False, secret=True)]),
    "modbus": dict(label="Modbus TCP", category="Plant systems", icon="plug", blurb="Meters and controllers", adapter=None,
                   fields=[F("host", "Host"), F("port", "Port", "number", default=502), F("unit_id", "Unit id", "number", default=1)]),
    "mqtt": dict(label="MQTT", category="Plant systems", icon="antenna", blurb="IoT sensors and gateways", adapter=None,
                 fields=[F("broker", "Broker", placeholder="mqtt://broker.plant.local:1883"), F("topic", "Topic", placeholder="plant/+/utilities/#"),
                         F("username", "User name", required=False), F("password", "Password", "password", required=False, secret=True)]),
    "bacnet": dict(label="BACnet", category="Plant systems", icon="building", blurb="Building management systems", adapter=None,
                   fields=[F("gateway", "Gateway"), F("device_id", "Device id", "number")]),
    "postgresql": dict(label="PostgreSQL", category="Databases", icon="database", blurb="Read a table or a query", adapter=SqlAdapter("postgresql"), verified=True,
                       fields=[*_DB_COMMON[:1], F("port", "Port", "number", default=5432), *_DB_COMMON[2:],
                               F("ssl", "Encryption", "select", required=False, default="require", options=["off", "require", "verify"],
                                 help="require encrypts without checking the certificate; verify also checks it")]),
    "mysql": dict(label="MySQL / MariaDB", category="Databases", icon="database", blurb="Read a table or a query", adapter=SqlAdapter("mysql"), verified=False,
                  fields=[*_DB_COMMON[:1], F("port", "Port", "number", default=3306), *_DB_COMMON[2:],
                          F("ssl", "Encryption", "select", required=False, default="off", options=["off", "require", "verify"])]),
    "sqlserver": dict(label="SQL Server", category="Databases", icon="database", blurb="Read a table or a query", adapter=SqlAdapter("sqlserver"), verified=False,
                      fields=[*_DB_COMMON[:1], F("port", "Port", "number", default=1433), *_DB_COMMON[2:]]),
    "rest_json": dict(label="REST API (JSON)", category="Business applications", icon="api", blurb="Any application with a web API", adapter=RestJsonAdapter(), verified=True,
                      fields=[F("url", "Address", placeholder="https://api.plant.local/v1/readings"), *_WEB_AUTH,
                              F("rows_path", "Where the rows are", required=False, placeholder="data.items",
                                help="The place in the answer that holds the list of records. Leave empty if the answer is the list.")]),
    "cmms": dict(label="CMMS", category="Business applications", icon="tool", blurb="Work orders and service intervals", adapter=None,
                 fields=[F("base_url", "Base address"), F("token", "Token", "password", secret=True)]),
    "mes": dict(label="MES", category="Business applications", icon="factory", blurb="Production counts and schedule", adapter=None,
                fields=[F("base_url", "Base address"), F("token", "Token", "password", secret=True)]),
    "sap": dict(label="SAP", category="Business applications", icon="building", blurb="Orders and materials", adapter=None,
                fields=[F("host", "Host"), F("client", "Client"), F("username", "User name"), F("password", "Password", "password", secret=True)]),
    "csv_url": dict(label="CSV by link", category="Files and links", icon="file", blurb="A CSV file at a web address", adapter=CsvUrlAdapter(), verified=True,
                    fields=[F("url", "Address", placeholder="https://files.plant.local/energy.csv"), *_WEB_AUTH]),
    "demo_gateway": dict(label="Demo plant gateway", category="Files and links", icon="bolt", blurb="Built-in sample source, no setup", adapter=DemoGateway(), verified=True, fields=[]),
}
SQLITE_TEST = SqlAdapter("sqlite")          # used only by the automated tests
CATEGORIES = ["Plant systems", "Databases", "Business applications", "Files and links"]
LIMIT = {"postgresql": 5000, "mysql": 5000, "sqlserver": 5000, "sqlite": 5000, "rest_json": 20000, "csv_url": 100000, "demo_gateway": 5000}


def adapter_for(kind: str) -> Adapter | None:
    if kind == "sqlite":
        return SQLITE_TEST
    return (KINDS.get(kind) or {}).get("adapter")


def catalog() -> list[dict]:
    out = []
    for key, k in KINDS.items():
        ok = k["adapter"] is not None
        out.append({"kind": key, "label": k["label"], "category": k["category"], "icon": k["icon"], "blurb": k["blurb"], "fields": k["fields"],
                    "available": ok, "verified": bool(k.get("verified")), "source_mode": key in ("postgresql", "mysql", "sqlserver"),
                    "note": "" if ok else NOTE_DRIVER if not k.get("verified") else ""})
    return out


def secret_keys(kind: str) -> set[str]:
    return {f["key"] for f in (KINDS.get(kind) or {}).get("fields", []) if f["secret"]}
