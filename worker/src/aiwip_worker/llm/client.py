"""LLM client: a real OpenAI Structured-Outputs client and a Fake for tests."""
from __future__ import annotations

import json
from dataclasses import dataclass

# Rough $/token pricing for cost logging (extend as models change).
_PRICING = {
    "gpt-4o-mini": (0.15 / 1_000_000, 0.60 / 1_000_000),
    "gpt-4o": (2.50 / 1_000_000, 10.0 / 1_000_000),
}


@dataclass
class LLMResult:
    output: dict | None
    raw_text: str
    model: str
    tokens_input: int
    tokens_output: int
    cost: float | None
    status: str  # success | invalid_json | error
    error: str | None = None


class OpenAIClient:
    def __init__(self, api_key: str | None = None, model: str | None = None):
        from aiwip_core.config import settings

        self._api_key = api_key or settings.openai_api_key
        self._model = model or settings.openai_model
        if not self._api_key:
            raise RuntimeError("OPENAI_API_KEY not set — add it to .env to run the AI pipeline.")
        self._client = None

    def _ensure(self):
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(api_key=self._api_key)
        return self._client

    def _cost(self, tokens_in: int, tokens_out: int) -> float | None:
        price = _PRICING.get(self._model)
        return round(tokens_in * price[0] + tokens_out * price[1], 6) if price else None

    def extract(self, system: str, user: str, schema: dict) -> LLMResult:
        try:
            resp = self._ensure().chat.completions.create(
                model=self._model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                response_format={"type": "json_schema", "json_schema": schema},
                temperature=0,
            )
            text = resp.choices[0].message.content or ""
            usage = getattr(resp, "usage", None)
            tin = getattr(usage, "prompt_tokens", 0) or 0
            tout = getattr(usage, "completion_tokens", 0) or 0
            cost = self._cost(tin, tout)
            try:
                output = json.loads(text)
            except json.JSONDecodeError as exc:
                return LLMResult(None, text, self._model, tin, tout, cost, "invalid_json", str(exc))
            return LLMResult(output, text, self._model, tin, tout, cost, "success")
        except Exception as exc:  # noqa: BLE001 — any API failure is logged, never crashes the pipeline
            return LLMResult(None, "", self._model, 0, 0, None, "error", str(exc))


class FakeLLMClient:
    """Deterministic client for tests."""

    def __init__(self, output: dict, status: str = "success", tokens: tuple[int, int] = (100, 50), model: str = "fake-model"):
        self._output = output
        self._status = status
        self._tokens = tokens
        self._model = model

    def extract(self, system: str, user: str, schema: dict) -> LLMResult:
        out = self._output if self._status == "success" else None
        raw = json.dumps(self._output) if out is not None else "<<not-json>>"
        return LLMResult(out, raw, self._model, self._tokens[0], self._tokens[1], 0.0, self._status)
