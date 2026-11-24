import json

from langchain_core.language_models.fake import FakeListLLM

from app.agent.agent import TOOL_MAP, build_llm, parse_action, run_agent


def _llm(*replies):
    return FakeListLLM(responses=[r if isinstance(r, str) else json.dumps(r) for r in replies])


def test_parse_action_variants():
    assert parse_action('{"action":"final","answer":"ok"}')["answer"] == "ok"
    assert parse_action('```json\n{"action":"detect_abnormal_usage","input":{}}\n```')["action"] == "detect_abnormal_usage"
    assert parse_action("Plain prose answer")["action"] == "final"
    assert parse_action('{"answer":"no action key"}')["action"] == "final"
    assert parse_action('{"action":"response","answer":"hi"}') == {"action": "final", "answer": "hi"}
    assert parse_action('{"action":"detect_abnormal_usage","input":"{\\"days\\": 3}"}')["input"] == '{"days": 3}'
    assert parse_action('{"action":"detect_abnormal_usage","days":3}')["input"] == {"days": 3}


def test_tool_then_final_with_events():
    events = []
    res = run_agent("How are utilities?", on_event=events.append, llm=_llm(
        {"action": "get_utility_health_board", "input": "{}"},
        {"action": "final", "answer": "Compressed air is in ALARM."}))
    assert res.answer == "Compressed air is in ALARM."
    assert res.steps[0]["tool"] == "get_utility_health_board" and res.steps[0]["ok"]
    assert '"overall_status"' in res.steps[0]["output"]
    assert [e["type"] for e in events] == ["thinking", "tool_start", "tool_end", "thinking"]
    assert res.duration_ms >= 0


def test_bad_tool_and_bad_args_are_reported_back():
    res = run_agent("x", llm=_llm(
        {"action": "open_valve", "input": {"valve": "V1"}},
        {"action": "detect_abnormal_usage", "input": {"system": "steam"}},
        {"action": "get_issue", "input": "{}"},
        {"action": "final", "answer": "done"}))
    assert res.steps[0]["output"].startswith("ERROR: unknown tool")
    assert "unknown argument" in res.steps[1]["output"]
    assert "missing required argument(s)" in res.steps[2]["output"]
    assert res.answer == "done"


def test_unknown_utility_is_a_tool_error_the_model_can_read():
    res = run_agent("x", llm=_llm({"action": "detect_abnormal_usage", "input": {"utility_type": "steam"}},
                                  {"action": "final", "answer": "ok"}))
    assert not res.steps[0]["ok"] and "Available: COMPRESSED_AIR, HVAC" in res.steps[0]["output"]


def test_repeat_call_blocked_and_step_limit_forces_final():
    call = {"action": "detect_abnormal_usage", "input": {"days": 5}}
    res = run_agent("x", max_steps=2, llm=_llm(call, call, {"action": "final", "answer": "summary"}))
    assert res.steps[1]["output"].startswith("NOTE: you already called")
    assert res.answer == "summary"


def test_no_actuation_tools_exist():
    forbidden = ("setpoint", "valve", "start", "stop", "actuate", "write_tag", "control")
    assert not [n for n in TOOL_MAP if any(f in n for f in forbidden)]


def test_system_prompt_contains_controls_and_tools():
    system = build_llm().system
    assert "advisory only" in system and "certified operators" in system
    assert all(name in system for name in TOOL_MAP)
    assert "relative load index" in system
