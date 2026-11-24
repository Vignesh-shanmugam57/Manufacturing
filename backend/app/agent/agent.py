"""Utilities Management Agent: LangChain prompt -> Domo LLM -> JSON action loop (setup guide 6.6).

Domo Text Generation has no native tool calling, so the model replies with one JSON action per turn:
    {"action": "<tool>", "input": {...}}   or   {"action": "final", "answer": "..."}
The loop runs the tool, appends the result to the scratchpad and asks again, up to AGENT_MAX_STEPS.
Progress events (thinking / tool_start / tool_end) can be streamed to the UI through `on_event`.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from langchain_core.language_models import BaseLLM
from langchain_core.output_parsers import StrOutputParser

from app.agent.domo_llm import DomoTextLLM
from app.agent.prompts import ACTION_SCHEMA, PROMPT, SYSTEM_PROMPT
from app.agent.tools import TOOLS
from app.core.config import settings
from app.db.session import SessionLocal
from app.services import analytics as an

log = logging.getLogger("utilities_agent.agent")

TOOL_MAP = {t.name: t for t in TOOLS}
OBS_LIMIT = 9000          # characters of each tool result kept in the scratchpad
STORED_OUTPUT_LIMIT = 2000
FINAL_ALIASES = {"final", "final_answer", "finish", "answer", "respond", "response", "reply", "done"}

EventCallback = Callable[[dict], None]


@dataclass
class AgentResult:
    answer: str
    steps: list[dict] = field(default_factory=list)
    usage: dict = field(default_factory=dict)       # llm_calls, input_tokens, output_tokens
    duration_ms: int = 0


def _signature(t) -> str:
    parts = []
    for name, p in t.args.items():
        typ = p.get("type", "any")
        parts.append(f"{name}: {typ} = {json.dumps(p['default'])}" if "default" in p else f"{name}: {typ}")
    desc = " ".join(t.description.split())
    return f"- {t.name}({', '.join(parts)}): {desc}"


TOOL_DOC = "\n".join(_signature(t) for t in TOOLS)


def build_llm() -> DomoTextLLM:
    system = (SYSTEM_PROMPT.replace("__SITE__", settings.site_name).replace("__TOOLS__", TOOL_DOC)
              .replace("__MAX_STEPS__", str(settings.agent_max_steps)))
    return DomoTextLLM(system=system, response_schema=ACTION_SCHEMA)


def parse_action(raw: str) -> dict:
    """Extract the first JSON object from the model reply; plain prose is treated as a final answer."""
    s = (raw or "").strip()
    if s.startswith("```"):
        s = s.strip("`")
        s = s[s.find("{"):] if "{" in s else s
    start = s.find("{")
    if start >= 0:
        try:
            obj, _ = json.JSONDecoder().raw_decode(s[start:])
        except json.JSONDecodeError:
            obj = None
        if isinstance(obj, dict):
            action = str(obj.get("action") or "").strip()
            if (not action or action.lower() in FINAL_ALIASES) and obj.get("answer"):
                return {"action": "final", "answer": obj["answer"]}
            if action:
                args = obj.get("input")
                extra = {k: v for k, v in obj.items() if k not in ("action", "input", "answer")}
                if not args and extra:  # arguments placed at the top level
                    args = extra
                return {"action": action, "input": args if args is not None else {}}
    return {"action": "final", "answer": s or "I could not produce an answer."}


def _validate_args(tool, args) -> tuple[dict | None, str | None]:
    usage = f"Usage: {_signature(tool)[2:].split('):')[0]})"
    if isinstance(args, str):
        try:
            args = json.loads(args) if args.strip() else {}
        except json.JSONDecodeError:
            return None, f"ERROR: input must be a JSON object of arguments. {usage}"
    if not isinstance(args, dict):
        return None, f"ERROR: input must be a JSON object of arguments. {usage}"
    unknown = set(args) - set(tool.args)
    if unknown:
        return None, f"ERROR: unknown argument(s) {sorted(unknown)} for {tool.name}. {usage}"
    missing = [n for n, p in tool.args.items() if "default" not in p and n not in args]
    if missing:
        return None, f"ERROR: missing required argument(s) {missing} for {tool.name}. {usage}"
    return args, None


def run_agent(question: str, history: list[dict] | None = None, max_steps: int | None = None,
              llm: BaseLLM | None = None, on_event: EventCallback | None = None) -> AgentResult:
    """Answer one user question. Raises DomoAPIError if the model cannot be reached."""
    t0 = time.perf_counter()
    max_steps = max_steps or settings.agent_max_steps
    model = llm or build_llm()
    chain = PROMPT | model | StrOutputParser()
    with SessionLocal() as s:
        latest = an.as_of(s)
        stored = (f"stored history ends {latest:%Y-%m-%d %H:%M}" if latest else "no history uploaded yet")
        as_of = f"{dt.datetime.now():%Y-%m-%d %H:%M} now (issues, team and usage are live); {stored}"
    hist = "\n".join(f"{m['role']}: {m['content'][:1500]}" for m in (history or [])[-10:]) or "(none)"
    scratch: list[str] = []
    steps: list[dict] = []
    seen: set[str] = set()

    def emit(event: dict) -> None:
        if on_event:
            try:
                on_event(event)
            except Exception:  # noqa: BLE001 - a UI callback must never break the agent
                log.exception("on_event callback failed")

    def ask(step: int, instruction: str) -> dict:
        emit({"type": "thinking", "step": step})
        raw = chain.invoke({"as_of": as_of, "history": hist, "question": question,
                            "scratchpad": "\n\n".join(scratch) or "(empty)", "instruction": instruction})
        log.debug("model: %s", raw)
        return parse_action(raw)

    def finish(answer: str) -> AgentResult:
        usage = getattr(model, "usage", {}) or {}
        return AgentResult(answer=answer.strip(), steps=steps, usage=usage,
                           duration_ms=int((time.perf_counter() - t0) * 1000))

    for i in range(1, max_steps + 1):
        act = ask(i, "Reply with your next JSON action.")
        name = act.get("action")
        if name == "final":
            return finish(str(act.get("answer") or ""))
        args = act.get("input") or {}
        tool = TOOL_MAP.get(name)
        ok = False
        if tool is None:
            obs = f"ERROR: unknown tool '{name}'. Valid tools: {', '.join(TOOL_MAP)} or 'final'."
        else:
            args, err = _validate_args(tool, args)
            key = f"{name}:{json.dumps(args, sort_keys=True)}"
            if err:
                obs = err
            elif key in seen:
                obs = "NOTE: you already called this tool with the same input. Use the earlier result."
            else:
                emit({"type": "tool_start", "step": i, "tool": name, "input": args})
                try:
                    obs = tool.invoke(args)
                    ok = not str(obs).startswith("ERROR")
                    seen.add(key)  # only successful calls count as duplicates
                except Exception as e:  # noqa: BLE001 - surface tool errors to the model
                    obs = f"ERROR: {e}"
        obs = str(obs)
        log.info("step %d: %s %s -> %d chars", i, name, args, len(obs))
        emit({"type": "tool_end", "step": i, "tool": name, "ok": ok})
        steps.append({"tool": name, "input": args, "output": obs[:STORED_OUTPUT_LIMIT], "ok": ok})
        clipped = obs if len(obs) <= OBS_LIMIT else obs[:OBS_LIMIT] + " ...[truncated]"
        scratch.append(f"[{i}] CALL {name} {json.dumps(args)}\nRESULT: {clipped}")

    act = ask(max_steps + 1, 'Tool limit reached. Reply now with {"action": "final", "answer": "..."} using only '
                             "the results above; say what could not be checked.")
    if act.get("action") == "final" and act.get("answer"):
        return finish(str(act["answer"]))
    return finish("I couldn't finish within the step limit. Try a narrower question.")
