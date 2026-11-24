# Utilities Management Agent (Agent 17/20)

An application for a plant team to look after the factory utilities (compressed air, steam, chilled water, cooling tower, HVAC, water, gas). It answers the questions the team asks every day:

- **What is wrong right now, and where?**
- **Who has to go, and how long has it been open?**
- **What should they do?**
- **Is our usage normal?**

It is a **proof of concept on mock data**. The live readings come from a built-in simulator, and the team roster, the incident history and the usage model are generated. Everything that is generated is labelled as such in the app.

- **Frontend:** React 19 (Vite), with a three.js 3D plant map
- **Backend:** FastAPI, with a LangChain agent on Domo AI
- **Database:** PostgreSQL on Neon (database `utilities`); a local SQLite file is used when `DATABASE_URL` is not set

## The pages

The menu has the plant team's pages first, then a collapsible group for setup.

| Page | What it does |
|---|---|
| **Issues** (opens first) | Every problem: what is wrong (reading against expected), where (zone and equipment), who has to go (name, role, extension, shift), how long it has been open (live timer), whether it is escalated, not acknowledged in time or overdue, and what to do. Open one for the full timeline. Acknowledge, reassign, add a note, record the fix, verify with telemetry, reopen. Filters for open/closed, severity and zone. When the assigned person's shift has ended it names who is on shift now. The menu badge counts issues that need attention. |
| **Plant map** | Interactive 3D plant. Equipment with an open issue shows that issue's severity, even when its live readings are normal. "Show on plant map" on an issue flies to its equipment. Demo controls inject a simulated fault. |
| **Plant overview** | One status tile per utility, usage today against yesterday and a normal range (or the last 7 days), and the issues that need attention first. Energy, production, maintenance and quality sit lower on the page, collapsed. |
| **Ask the agent** | Chat in plain language. The agent reads the same live issues, roster and usage as the pages (see *The chat agent*). |
| **Data connectors** | Connect your own systems and pull from them (see *Connectors*), plus the stored data, the CSV upload and the mock-data buttons. |
| **Agent activity** | What the agent did (detections, hand-offs to the person on shift, escalations, verifications) and the nine steps behind any issue. A second tab, *History analysis*, is the read-only analysis of the stored CSV history. |
| **How it works** | An animated flow of the data path and of what happens when the agent finds a problem, with live figures. |

## Setup

You need [uv](https://docs.astral.sh/uv/) and Node.js 20+.

```powershell
cd utilities-agent\backend
uv sync
cd ..\frontend
npm install
```

`backend\.env` holds the Domo settings and `DATABASE_URL`, the Neon connection string with `/utilities` as the database. It is gitignored; keep it out of anything you share.

```
DATABASE_URL=postgresql://<user>:<password>@<endpoint>-pooler.<region>.aws.neon.tech/utilities?sslmode=require&channel_binding=require
```

```powershell
cd utilities-agent\backend
uv run python cli.py --create-database   # creates "utilities" on Neon if missing
uv run python cli.py --init-db           # creates the tables (every app start also does this)
uv run python cli.py --seed-mock         # the mock team and incident history (about 20 s)
```

Other settings (all optional, in `.env`):

| Setting | Meaning |
|---|---|
| `CONNECTOR_SECRET_KEY` | Fernet key that encrypts connector passwords. If empty, one is generated into `backend\data\connector.key` the first time a password is stored. Keep it private. |
| `CONNECTOR_ALLOWED_HOSTS` | Comma separated hosts the REST and CSV connectors may call. Empty allows any host except link-local and cloud-metadata addresses. Set it before real use. |
| `CONNECTORS_AUTORUN` | `false` stops scheduled pulls (the tests do this). |
| `TWIN_AUTOSTART` | `false` stops the telemetry engine. |

### Load the stored data (optional)

The stored CSV history feeds the history analysis, the chat agent's history tools and the collapsed plant context. Use the **Data connectors** page (drag the files into *Stored data and file upload*), or the CLI:

```powershell
uv run python cli.py --load ..\csv-data\fact_utility_telemetry_hourly.csv ..\csv-data\fact_machine_telemetry_hourly.csv ..\csv-data\fact_downtime_event.csv
uv run python cli.py --status
```

- The file type is recognised from its header, so file names do not matter. There are 11 dataset types (see the `docs\` folder for the formats).
- Rows are validated one by one. Bad rows are skipped and reported, and the upload is saved as one transaction.
- Uploading a file again is safe: rows whose id is already stored are skipped. Tick **Replace existing rows** (or `--replace`) to start a dataset over.
- Neon is far from many networks. After a restart the server needs a minute or two to load the rows into memory; the history pages are slow until then.

## Run (development)

```powershell
# terminal 1
cd utilities-agent\backend
uv run python -m uvicorn app.main:app --reload --port 8000

# terminal 2
cd utilities-agent\frontend
npm run dev                                   # http://localhost:5173
```

Vite forwards `/api` to FastAPI. `--reload` does not re-read `backend\.env`: restart the server after changing it.

**Single server:** run `npm run build` in `frontend`, then start only the backend. FastAPI serves the built app at http://localhost:8000. Run **one** server process: the telemetry engine and the connector scheduler keep state in memory.

## Project layout

```
utilities-agent/
├── backend/                     Python (uv)
│   ├── cli.py                   CLI: load CSVs, status, health board, scan, chat, --seed-mock, --clear-mock
│   ├── app/
│   │   ├── main.py              FastAPI app: routers, startup (telemetry engine, connector scheduler), serves frontend/dist
│   │   ├── agent/               Domo LLM, JSON-action loop, prompts, tools.py (history tools), plant_tools.py (live tools)
│   │   ├── api/routes/          health, users, sessions, chat, data, utilities, alerts, plant, twin, connectors, demo
│   │   ├── twin/                catalog (equipment, tags, limits), simulator, detectors, engine (alert lifecycle),
│   │   │                        people (roster routing), issues, usage, agent_activity, mock (seed data)
│   │   ├── connectors/          registry, sql, web (REST, CSV), demo, safety, secrets, service, scheduler
│   │   ├── services/            ingest (CSV upload), analytics (history analysis), legacy alerts
│   │   └── models/              chat, plant, operations, twin, connectors
│   └── tests/                   pytest (temporary SQLite database)
├── frontend/
│   ├── src/components/          Issues, twin/ (3D map), flow/ (Plant overview, How it works), Connectors, AgentActivity, ChatView ...
│   └── e2e/app.spec.js          Playwright end-to-end tests (Microsoft Edge)
├── csv-data/                    the three original sample CSV files
└── docs/                        sample files for all 11 dataset types
```

## How the pieces fit

**Telemetry and issues.** `backend/app/twin/engine.py` runs a 1 Hz loop over 23 pieces of equipment and 106 sensor tags. Deterministic rules (`detectors.py`, no LLM) turn threshold breaches and fault patterns into **issues**. Each issue records its own analysis (collected, validated, mapped, detected, root cause, impact, recommendation, alert, verification), a maintenance task, notifications and an audit trail of every action. An issue closes only when fresh readings stay inside their limits; nobody can mark it verified by hand.

**Who goes.** A new issue goes to the person on shift (`twin/people.py`): the team that owns the utility first, then the utilities engineer, the shift supervisor and the plant manager. Within a team someone who covers the zone comes first. The roster is the `twin_people` table (mock data).

**Escalation.** A critical issue not acknowledged in 2 minutes, or a major one in 5, escalates to the plant manager or the operations supervisor.

**Mock data.** `cli.py --seed-mock`, `POST /api/twin/mock/seed` or the button on the Data connectors page re-creates 17 people and about 30 incidents (26 closed, 6 open) with timestamps relative to now. They are tagged `MOCK`, so the demo reset never deletes them and the live rules never auto-close them. Seed again before a demo so the timers and shifts look current.

**Usage.** The plant has no metered history for all seven utilities, so `twin/usage.py` uses a day-shaped model that deviates while an issue is open. The chart is labelled *Mock usage data*.

**Live readings.** Telemetry comes from the simulator and is labelled SIMULATED. A real gateway replaces it by posting readings to `POST /api/twin/ingest` (`{"readings":[{"tag":"CA-HDR-A.pressure_bar","value":6.82}]}`) after switching the live feed to *live*; equipment that stops reporting turns grey after 15 s. The limits shipped are **demo limits**: replace them with site-engineered values before real use.

## Connectors

The **Data connectors** page connects the app to a client's own systems and pulls from them directly: choose a system, enter read-only details, test (with a sample of the rows), match the fields to a destination, and set a schedule (every minute to every hour, or on request).

| Connector | Status |
|---|---|
| PostgreSQL | Working. Tested against a real server (Neon). |
| REST API (JSON), CSV by link | Working. Tested against mocked servers and the app's own sample address. |
| Demo plant gateway | Working. A built-in source that needs no setup. |
| MySQL / MariaDB, SQL Server | Driver installed. **Not yet tested against a live server.** |
| OPC UA, Modbus TCP, MQTT, BACnet, CMMS, MES, SAP | Form only. The driver is added per project. Testing says so honestly. |

Read only, by design: SQL is limited to one SELECT, web calls are GET only, passwords are encrypted, pulled rows go through the same validated importer as the CSV upload (rows already stored are skipped, so a pull can be repeated safely), and web connectors refuse link-local and cloud-metadata addresses. SQL connections are opened read-only where the database supports it; use a database account that can only read.

`/api/demo/utility.json` and `/api/demo/utility.csv` serve sample readings (no sign-in, fake data) so a REST or CSV connection can be shown working against this app itself. Pulling them adds readings with today's dates to the *Utility telemetry* dataset (ids start `UT-DEMO-`), which distorts the history analysis; delete those rows when the demo is over.

## The chat agent

The agent is **advisory only**. It has no tool that changes setpoints or operates equipment, and it cannot raise, assign or close issues either; people do that on the Issues page. All numbers come from code, never from the model.

- **Live tools** (`agent/plant_tools.py`): `get_plant_status`, `list_open_issues`, `get_issue`, `get_team_on_shift`, `get_usage_vs_normal`, `get_issue_history`. They read the same issues, roster and usage as the pages.
- **History tools** (`agent/tools.py`): data overview, utility health board, consumption trends, abnormal usage, downtime correlation, efficiency recommendations, and a read-only `run_sql` (SELECT only).

An answer takes about 20 to 40 seconds, mostly the language model.

## How the history analysis works

All numbers are computed by code (`app/services/analytics.py`), never by the LLM.

- **Abnormal usage:** each plant/utility/zone series' last N days are compared with its own earlier history (Welch z-test plus a minimum change: flow 10 %, pressure 5 %, temperature 10 %), and alarm clusters are tested with an exact Poisson tail. A series with no recent readings is skipped. When nothing is abnormal, the agent says so.
- **Downtime link:** for each plant-hour, "after alarm" means a utility alarm at that plant in the same or previous 2 hours. Downtime start rates after alarms are compared with other hours (lift at least 1.5, z at least 2.5, at least 10 events). None of the downtime reason codes names a utility cause, so the link is timing-based and is a lead, not proof.
- **Efficiency:** does utility demand fall when machines are idle or down, is night load lower than day load, which zones use more than their peers, which equipment alarms more than the rest.

What the sample data does and does not allow:

- `consumption_unit` changes row by row (m3, L, kWh) for the same utility, so `flow_rate` is a relative load index. No absolute volumes or costs are reported from it.
- There are no site-engineered operating limits in the files, so "abnormal" means different from the series' own history, plus the alarms the plant raised.
- `PRESSURE_LOW` alarms occur at normal pressure in the sample files: the alarm configuration or sensors are worth checking.
- Each series has a reading about every 4 hours, so short windows contain few readings.

## API

All endpoints except health, login and `/api/demo/*` need the `X-User-Id` header that login returns. Interactive docs are at http://localhost:8000/docs.

| Area | Endpoints |
|---|---|
| Health, users | `GET /api/health`, `POST /api/users/login`, `GET /api/users/me` |
| Chat | `GET/POST /api/sessions`, `GET/PATCH/DELETE /api/sessions/{id}`, `POST /api/chat`, `POST /api/chat/stream` (Server-Sent Events) |
| Issues | `GET /api/twin/issues` (`status`, `severity`, `zone`, `assignee`), `GET /api/twin/issues/summary`, `GET /api/twin/issues/{id}`, `POST /api/twin/alerts/{id}/actions` (acknowledge, assign, investigate, comment, corrective_action, verify, reopen) |
| Team and usage | `GET /api/twin/people`, `GET /api/twin/overview`, `GET /api/twin/usage?utility=`, `GET /api/twin/agent/activity` |
| Plant | `GET /api/twin/snapshot`, `GET /api/twin/stream` (one snapshot a second), `GET /api/twin/equipment`, `GET /api/twin/maintenance`, `GET /api/twin/notifications`, `GET /api/twin/audit` |
| Simulation and setup | `POST /api/twin/scenarios/start\|fix\|reset`, `PUT /api/twin/mode`, `POST /api/twin/ingest`, `GET/PUT /api/twin/limits`, `POST /api/twin/mock/seed`, `DELETE /api/twin/mock` |
| Connectors | `GET /api/connectors/catalog`, `POST /api/connectors/test`, `POST /api/connectors/suggest-mapping`, `GET/POST /api/connectors`, `PATCH/DELETE /api/connectors/{id}`, `POST /api/connectors/{id}/pull`, `GET /api/connectors/{id}/runs` |
| Stored data | `GET /api/data/status`, `POST /api/data/upload`, `DELETE /api/data/{dataset}` |
| History analysis (no LLM) | `GET /api/utilities/health-board`, `overview`, `trends`, `anomalies`, `downtime-correlation`, `efficiency`, `GET /api/plant/summary` |
| Older alert list | `/api/alerts` (the original CSV-based alerts; the pages no longer use it) |

There is no endpoint that changes setpoints or operates equipment; tests assert it.

**Security, honestly.** Sign-in is lightweight: it asks for an email and name only, with no password, and every signed-in user can do everything (there are no permission levels yet). That is fine for a demo on a trusted network. **Before real use put single sign-on or accounts in front of it, add permission levels for the risky actions (connectors, mock data, deleting datasets, limits and the live-feed mode), and set `CONNECTOR_ALLOWED_HOSTS`.** Times are stored without a time zone (server local time).

## Database

| Table | Contents |
|---|---|
| `users`, `chat_sessions`, `chat_messages` | accounts, chats and the tool trace of every answer |
| `utility_readings`, `machine_readings`, `downtime_events`, plus energy, production, maintenance, quality and asset tables | the stored CSV history (11 dataset types) |
| `data_uploads`, `utility_alerts` | upload audit log; the original CSV-based alerts |
| `twin_equipment`, `twin_alerts`, `twin_alert_events`, `twin_maintenance`, `twin_notifications` | the equipment master, issues, their audit trail, tasks and notifications |
| `twin_people` | the team roster (shift, zones, extension) |
| `twin_readings`, `twin_settings` | downsampled telemetry history (7 days) and settings |
| `data_connectors`, `connector_runs` | saved connections (passwords encrypted) and a log of every pull |

## Tests

```powershell
cd utilities-agent\backend
uv run python -m pytest -q                       # 112 tests on a temporary SQLite DB
$env:TEST_DATABASE_URL="postgresql://user:pass@host/utilities_test"
uv run python -m pytest -q                       # same suite on PostgreSQL (DB name must contain "test")

cd ..\frontend
npm run build
$env:E2E_BASE_URL="http://localhost:8000"        # test a server you started yourself (it re-creates the mock data first)
npx playwright test                              # end-to-end tests in Edge, with live Domo calls for the chat
```

The backend tests use synthetic CSVs (`tests/factory.py`) with known planted patterns to prove the analysis finds what is there and stays quiet when nothing is. The end-to-end tests drive the real app, so they write to the database they point at (they re-create the mock data and acknowledge one issue). Screenshots are written to `frontend\test-results\screens`.

## Notes for this Windows PC

Smart App Control blocks some unsigned native files:

- **Run tools as modules.** It blocks the `.exe` launchers uv creates, so use `uv run python -m uvicorn` and `uv run python -m pytest`, and run Vite with `node node_modules\vite\bin\vite.js`.
- **Database driver.** It also blocks psycopg's libpq DLL, so the backend falls back automatically to **pg8000**, a pure-Python driver. On Linux servers, psycopg is used.
- **Connector drivers** are pure Python (`pymysql`, `python-tds`), and `cryptography` loads normally here.

**Domo:** structured output needs `"responseFormat": {"type": "JSON"}` with an upper-case type. Tool arguments are requested as a JSON string, because Domo's constrained decoding sometimes dropped a free-form object.
