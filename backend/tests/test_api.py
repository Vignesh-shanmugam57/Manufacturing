"""API tests through FastAPI's TestClient with a scripted LLM in place of Domo."""
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.llms import LLM
from pydantic import Field

import app.agent.agent as agent_module
from app.agent.domo_llm import DomoAPIError
from app.main import app


NOT_A_DATASET = b"a,b\n1,2\n"


class ScriptedLLM(LLM):
    """Returns scripted replies and records every prompt it was given."""
    replies: list[str] = Field(default_factory=list)
    prompts: list[str] = Field(default_factory=list)
    fail: bool = False

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _call(self, prompt: str, stop=None, run_manager=None, **kwargs: Any) -> str:
        if self.fail:
            raise DomoAPIError("Domo API 403: forbidden")
        self.prompts.append(prompt)
        return self.replies.pop(0) if self.replies else '{"action": "final", "answer": "default"}'


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def script(monkeypatch):
    """script(reply, ...) -> the ScriptedLLM that the next agent run will use."""
    def install(*replies, fail=False):
        llm = ScriptedLLM(replies=[r if isinstance(r, str) else json.dumps(r) for r in replies], fail=fail)
        monkeypatch.setattr(agent_module, "build_llm", lambda: llm)
        return llm
    return install


def login(client, email="ops.engineer@example.com", name="Ops Engineer"):
    r = client.post("/api/users/login", json={"email": email, "name": name, "role": "Utilities engineer"})
    assert r.status_code == 200, r.text
    return {"X-User-Id": r.json()["id"]}


def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok" and body["database_ok"] is True


def test_login_validation_and_upsert(client):
    assert client.post("/api/users/login", json={"email": "not-an-email", "name": "X"}).status_code == 422
    assert client.post("/api/users/login", json={"email": "a@b.co", "name": "   "}).status_code == 422
    first = client.post("/api/users/login", json={"email": "Pat@Example.com", "name": "Pat"}).json()
    again = client.post("/api/users/login", json={"email": "pat@example.com", "name": "Pat Lee"}).json()
    assert first["id"] == again["id"] and again["name"] == "Pat Lee" and again["email"] == "pat@example.com"
    assert client.get("/api/users/me", headers={"X-User-Id": first["id"]}).json()["name"] == "Pat Lee"


def test_endpoints_require_a_user(client):
    assert client.get("/api/sessions").status_code == 401
    assert client.get("/api/sessions", headers={"X-User-Id": "nope"}).status_code == 401
    assert client.get("/api/utilities/health-board").status_code == 401
    assert client.post("/api/chat", json={"message": "hi"}).status_code == 401


def test_chat_persists_session_messages_and_trace(client, script):
    h = login(client)
    script({"action": "get_utility_health_board", "input": "{}"},
           {"action": "final", "answer": "Chilled water is in WARNING."})
    r = client.post("/api/chat", json={"message": "Give me a status overview of plant utilities"}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["assistant_message"]["content"] == "Chilled water is in WARNING."
    assert body["assistant_message"]["steps"][0]["tool"] == "get_utility_health_board"
    assert body["assistant_message"]["duration_ms"] is not None
    sid = body["session"]["id"]
    assert body["session"]["title"] == "Give me a status overview of plant utilities"
    assert body["session"]["message_count"] == 2

    sessions = client.get("/api/sessions", headers=h).json()
    assert sessions[0]["id"] == sid and sessions[0]["message_count"] == 2
    detail = client.get(f"/api/sessions/{sid}", headers=h).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    assert detail["messages"][1]["steps"][0]["ok"] is True


def test_answer_without_tools_stores_sql_null_steps(client, script):
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models import ChatMessage

    h = login(client)
    script({"action": "final", "answer": "I can't change setpoints; certified operators handle that."})
    mid = client.post("/api/chat", json={"message": "Raise the steam setpoint"}, headers=h).json()["assistant_message"]["id"]
    with SessionLocal() as db:
        assert db.scalar(select(ChatMessage.id).where(ChatMessage.id == mid, ChatMessage.steps.is_(None))) == mid


def test_follow_up_sends_history_to_the_model(client, script):
    h = login(client)
    script({"action": "final", "answer": "First answer about steam."})
    sid = client.post("/api/chat", json={"message": "How is steam?"}, headers=h).json()["session"]["id"]
    llm = script({"action": "final", "answer": "Follow-up answer."})
    r = client.post("/api/chat", json={"session_id": sid, "message": "And what should we do?"}, headers=h)
    assert r.json()["session"]["message_count"] == 4
    assert "user: How is steam?" in llm.prompts[0] and "assistant: First answer about steam." in llm.prompts[0]


def test_sessions_are_private_and_editable(client, script):
    owner, other = login(client, "owner@example.com", "Owner"), login(client, "other@example.com", "Other")
    sid = client.post("/api/sessions", json={}, headers=owner).json()["id"]
    assert client.get(f"/api/sessions/{sid}", headers=other).status_code == 404
    assert client.patch(f"/api/sessions/{sid}", json={"title": "x"}, headers=other).status_code == 404
    assert client.delete(f"/api/sessions/{sid}", headers=other).status_code == 404
    assert client.post("/api/chat", json={"session_id": sid, "message": "hi"}, headers=other).status_code == 404
    assert all(s["id"] != sid for s in client.get("/api/sessions", headers=other).json())

    assert client.patch(f"/api/sessions/{sid}", json={"title": "Steam review"}, headers=owner).json()["title"] \
        == "Steam review"
    assert client.delete(f"/api/sessions/{sid}", headers=owner).status_code == 204
    assert client.get(f"/api/sessions/{sid}", headers=owner).status_code == 404


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if not line.startswith(":"))
        if fields:
            events.append((fields["event"], json.loads(fields["data"])))
    return events


def test_stream_emits_progress_then_final(client, script):
    h = login(client)
    script({"action": "detect_abnormal_usage", "input": '{"utility_type": "compressed_air", "days": 5}'},
           {"action": "final", "answer": "Compressed air in P1 SMT is 40% up."})
    r = client.post("/api/chat/stream", json={"message": "Any air leaks?"}, headers=h)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(r.text)
    types = [t for t, _ in events]
    assert types == ["session", "thinking", "tool_start", "tool_end", "thinking", "final"]
    assert events[2][1]["tool"] == "detect_abnormal_usage"
    final = events[-1][1]
    assert final["assistant_message"]["content"] == "Compressed air in P1 SMT is 40% up."
    assert final["session"]["id"] == events[0][1]["session"]["id"]
    assert client.post("/api/chat/stream", json={"session_id": "missing", "message": "x"}, headers=h).status_code == 404


def test_domo_failure_is_saved_as_error_and_excluded_from_history(client, script):
    h = login(client)
    script(fail=True)
    body = client.post("/api/chat", json={"message": "status?"}, headers=h).json()
    assert body["assistant_message"]["is_error"] is True and "403" in body["assistant_message"]["content"]
    llm = script({"action": "final", "answer": "ok"})
    client.post("/api/chat", json={"session_id": body["session"]["id"], "message": "retry"}, headers=h)
    assert "403" not in llm.prompts[0]


def test_utilities_views_and_alert_workflow(client):
    h = login(client, "maint.planner@example.com", "Maint Planner")
    hb = client.get("/api/utilities/health-board", headers=h).json()
    assert hb["overall_status"] == "ALARM" and len(hb["utilities"]) == 2 and "open_alerts" in hb
    assert client.get("/api/utilities/overview", headers=h).json()["plants"] == ["P1", "P2"]
    tr = client.get("/api/utilities/trends?utility_type=hvac&period=week&periods=3", headers=h).json()
    assert tr["groups"][0]["group"] == "HVAC"
    an_ = client.get("/api/utilities/anomalies?days=5&utility_type=compressed_air", headers=h).json()
    assert an_["anomaly_count"] >= 1
    assert client.get("/api/utilities/anomalies?utility_type=steam", headers=h).status_code == 400
    corr = client.get("/api/utilities/downtime-correlation?window_hours=2", headers=h).json()
    assert corr["by_utility_type"][0]["utility_type"] == "HVAC"
    assert client.get("/api/utilities/efficiency", headers=h).json()["recommendations"]

    client.post("/api/utilities/scan", headers=h)
    alerts = client.get("/api/alerts?status=open", headers=h).json()["alerts"]
    assert alerts
    aid = alerts[0]["id"]
    acked = client.post(f"/api/alerts/{aid}/status", json={"status": "ACKNOWLEDGED", "note": "on it"}, headers=h).json()
    assert acked["status"] == "ACKNOWLEDGED" and acked["acknowledged_at"]
    assert client.post(f"/api/alerts/{aid}/status", json={"status": "VERIFIED"}, headers=h).status_code == 422
    assert client.post(f"/api/alerts/{aid}/status", json={"status": "ACKNOWLEDGED"}, headers=h).status_code == 400
    assert "normal" in client.post(f"/api/alerts/{aid}/verify", headers=h).json()
    assert client.post("/api/alerts/99999/verify", headers=h).status_code == 400


def test_upload_flow_status_errors_and_empty_state(client):
    from tests.conftest import load_all
    from tests.factory import make_csvs

    h = login(client, "data.owner@example.com", "Data Owner")
    assert client.get("/api/data/status").status_code == 401
    assert client.post("/api/data/upload", files={"file": ("x.csv", NOT_A_DATASET)}).status_code == 401

    st = client.get("/api/data/status", headers=h).json()
    from app.services import ingest as _ingest
    loaded = {"utility", "machine", "downtime"}          # the test database holds only these three; the other eight datasets are empty
    assert {d["dataset"]: d["rows"] > 0 for d in st["datasets"]} == {k: k in loaded for k in _ingest.DATASETS}
    assert st["as_of"].startswith("2026-09-30") and st["data_quality"]

    # bad files -> 400 with a readable reason
    r = client.post("/api/data/upload", files={"file": ("x.csv", NOT_A_DATASET)}, headers=h)
    assert r.status_code == 400 and "does not match any dataset" in r.json()["detail"]
    r = client.post("/api/data/upload", files={"file": ("x.csv", b"utility_reading_id,timestamp\nU1,2026-01-01\n")},
                    headers=h)
    assert r.status_code == 400 and "missing column" in r.json()["detail"]

    try:
        # empty database -> friendly empty state, not a crash
        for ds in ("utility", "machine", "downtime"):
            assert client.delete(f"/api/data/{ds}", headers=h).json()["deleted"] > 0
        assert client.delete("/api/data/nope", headers=h).status_code == 400
        assert client.get("/api/utilities/health-board", headers=h).json()["empty"] is True
        assert "Upload" in client.get("/api/utilities/anomalies", headers=h).json()["detail"]

        # upload the three files through the API
        for key, data in make_csvs().items():
            r = client.post("/api/data/upload", files={"file": (f"{key}.csv", data, "text/csv")}, data={"mode": "append"}, headers=h)
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["dataset"] == key and body["inserted"] == body["rows_in_file"] and body["invalid_skipped"] == 0
        again = client.post("/api/data/upload", files={"file": ("u.csv", make_csvs()["downtime"])}, headers=h).json()
        assert again["inserted"] == 0 and again["duplicates_skipped"] == again["rows_in_file"]
        assert client.post("/api/data/upload", files={"file": ("u.csv", make_csvs()["downtime"])},
                           data={"mode": "weird"}, headers=h).status_code == 422
        assert client.get("/api/utilities/health-board", headers=h).json()["empty"] is False
    finally:
        load_all()


def test_manual_alert_creation(client):
    h = login(client, "alert.author@example.com", "Alert Author")
    body = {"utility_type": "hvac", "plant_id": "p2", "zone": "smt", "title": "Morning HVAC alarm check",
            "severity": "LOW", "recommendation": "Review alarm set-points", "assigned_to": "facilities"}
    r = client.post("/api/alerts", json=body, headers=h)
    assert r.status_code == 201 and r.json()["created"] is True
    alert = r.json()["alert"]
    assert (alert["utility_type"], alert["plant_id"], alert["zone"], alert["source"]) == ("HVAC", "P2", "SMT", "user")
    again = client.post("/api/alerts", json=body, headers=h).json()
    assert again["created"] is False and again["alert"]["id"] == alert["id"]
    assert client.post("/api/alerts", json={**body, "severity": "URGENT"}, headers=h).status_code == 422
    assert client.post("/api/alerts", json={**body, "utility_type": "steam"}, headers=h).status_code == 400
    assert client.post("/api/alerts", json=body).status_code == 401
