"""Domo AI Text Generation endpoint as a LangChain LLM (setup guide section 6.4).

Usable anywhere LangChain expects an LLM:  PROMPT | DomoTextLLM() | StrOutputParser()
Adds: system message, structured JSON output (responseFormat), retries and token-usage tracking.
"""
from __future__ import annotations

import logging
import time
from typing import Any, List, Optional

import httpx
from langchain_core.language_models.llms import LLM
from pydantic import PrivateAttr

from app.core.config import settings

log = logging.getLogger("utilities_agent.domo")

_client = httpx.Client(timeout=settings.llm_timeout_seconds)


class DomoAPIError(RuntimeError):
    pass


class DomoTextLLM(LLM):
    temperature: float = settings.llm_temperature
    max_tokens: int = settings.llm_max_tokens
    system: Optional[str] = None
    response_schema: Optional[dict] = None   # JSON schema -> Domo responseFormat {"type": "JSON", ...}
    max_retries: int = 2

    _usage: dict = PrivateAttr(default_factory=lambda: {"llm_calls": 0, "input_tokens": 0, "output_tokens": 0})

    @property
    def usage(self) -> dict:
        """Accumulated Domo calls and tokens for this LLM instance (one instance per agent run)."""
        return dict(self._usage)

    @property
    def _llm_type(self) -> str:
        return "domo-text-generation"

    @property
    def _identifying_params(self) -> dict:
        return {"model": settings.model_name, "temperature": self.temperature, "max_tokens": self.max_tokens}

    def _call(self, prompt: str, stop: Optional[List[str]] = None, run_manager=None, **kwargs: Any) -> str:
        if not settings.domo_developer_token:
            raise DomoAPIError("DOMO_DEVELOPER_TOKEN is not set (see backend/.env).")
        payload: dict = {"input": prompt, "temperature": self.temperature, "maxTokens": self.max_tokens}
        if settings.model_name:
            payload["model"] = settings.model_name
        if self.system:
            payload["system"] = self.system
        if self.response_schema and settings.domo_structured_output:
            # Domo expects the upper-case type "JSON"; lower-case "json" is rejected with 400.
            payload["responseFormat"] = {"type": "JSON", "schema": self.response_schema}

        data = self._post(payload)
        out = data.get("output")
        if out is None and data.get("choices"):
            out = data["choices"][0].get("output")
        out = out or ""
        usage = data.get("modelProviderUsage") or {}
        self._usage["llm_calls"] += 1
        self._usage["input_tokens"] += usage.get("inputTokens") or 0
        self._usage["output_tokens"] += usage.get("outputTokens") or 0
        log.info("domo model=%s in=%s out=%s tokens", data.get("modelId"), usage.get("inputTokens"),
                 usage.get("outputTokens"))
        for s in stop or []:
            out = out.split(s)[0]
        return out

    def _post(self, payload: dict) -> dict:
        url = f"{settings.domo_base_url.rstrip('/')}/api/ai/v1/text/generation"
        headers = {"X-DOMO-Developer-Token": settings.domo_developer_token, "Content-Type": "application/json"}
        for attempt in range(self.max_retries + 1):
            try:
                r = _client.post(url, json=payload, headers=headers)
            except httpx.TransportError as e:
                if attempt < self.max_retries:
                    time.sleep(2 ** attempt)
                    continue
                raise DomoAPIError(f"Cannot reach Domo at {url}: {e}") from e
            if r.status_code == 200:
                return r.json()
            if r.status_code == 400 and "responseFormat" in payload:
                log.warning("Domo rejected responseFormat; retrying without structured output.")
                payload = {k: v for k, v in payload.items() if k != "responseFormat"}
                continue
            if r.status_code in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                time.sleep(2 ** attempt)
                continue
            hint = {403: "check DOMO_DEVELOPER_TOKEN and that MODEL_NAME is enabled for Text Generation",
                    409: "model/session configuration conflict"}.get(r.status_code, "")
            raise DomoAPIError(f"Domo API {r.status_code}: {r.text[:300]} {hint}".strip())
        raise DomoAPIError("Domo API: retries exhausted.")
