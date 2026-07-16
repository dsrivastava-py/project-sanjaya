"""Groq API client (PRD §9.1). A thin transport over the OpenAI-compatible Groq
endpoint that wraps every call with:

  * redaction of the outbound system/user strings (§9.2) + optional debug dump;
  * JSON mode (``response_format={"type":"json_object"}``) when asked;
  * retries — 3 attempts, exponential backoff 2s/8s/30s, honoring ``Retry-After``
    on 429 (§9.1);
  * daily token accounting into the budget counter (§9.4).

The client never logs the API key. It is only constructed when a key exists; a
missing key raises :class:`GroqError`, which callers treat as "offline" and
leave the work queued.
"""
from __future__ import annotations

import json
import time

from .. import env
from ..db import get_setting
from ..log import get
from ..timeutil import now_ts
from . import budget, redact

_log = get("ai.groq")
BASE_URL = "https://api.groq.com/openai/v1"
_BACKOFF = (2, 8, 30)


class GroqError(RuntimeError):
    pass


def _retry_after(exc) -> float | None:
    """Best-effort parse of a 429 ``Retry-After`` header (seconds)."""
    resp = getattr(exc, "response", None)
    headers = getattr(resp, "headers", None) or {}
    val = headers.get("retry-after") or headers.get("Retry-After")
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None


class GroqClient:
    def __init__(self, cfg, *, api_key: str | None = None, sleep=time.sleep):
        self._cfg = cfg
        self._api_key = api_key if api_key is not None else env.groq_api_key()
        self._sleep = sleep
        self._client = None

    def _ensure(self):
        if self._client is None:
            if not self._api_key:
                raise GroqError("GROQ_API_KEY not set")
            from openai import OpenAI
            self._client = OpenAI(api_key=self._api_key, base_url=BASE_URL)
        return self._client

    def _patterns(self, conn):
        raw = get_setting(conn, "redaction_patterns", None)
        try:
            pats = json.loads(raw) if raw else []
        except (TypeError, ValueError):
            pats = []
        return redact.compile_patterns(pats)

    def complete(self, conn, *, kind: str, model: str, system: str, user: str,
                 json_mode: bool = True, temperature: float = 0.2) -> dict:
        """Run one completion. Returns ``{data, text, total_tokens}`` where
        ``data`` is the parsed JSON object (or None when not in JSON mode)."""
        compiled = self._patterns(conn)
        system = redact.redact_text(system, compiled)
        user = redact.redact_text(user, compiled)
        dbg = get_setting(conn, "debug_ai_payloads", None)
        debug_on = (str(dbg).lower() in ("1", "true", "yes", "on")) if dbg is not None \
            else bool(self._cfg.get("ai", "debug_ai_payloads", False))
        if debug_on:
            redact.dump_payload(kind, now_ts(), system, user)

        client = self._ensure()
        kwargs = {
            "model": model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        resp = self._call_with_retries(client, kwargs)
        text = (resp.choices[0].message.content or "") if resp.choices else ""
        usage = getattr(resp, "usage", None)
        total = int(getattr(usage, "total_tokens", 0) or 0)
        budget.add_tokens(conn, self._cfg, total)

        data = None
        if json_mode:
            try:
                data = json.loads(text)
            except ValueError as e:
                raise GroqError(f"model returned non-JSON: {e}") from e
        return {"data": data, "text": text, "total_tokens": total}

    def _call_with_retries(self, client, kwargs):
        last = None
        for i in range(3):
            try:
                return client.chat.completions.create(**kwargs)
            except Exception as e:  # noqa: BLE001 - normalize all SDK errors
                last = e
                if i == 2:
                    break
                wait = _BACKOFF[i]
                ra = _retry_after(e)
                if ra is not None:
                    wait = max(wait, ra)
                _log.warning("groq call failed (attempt %d/3): %s; retrying in %ss",
                             i + 1, e, wait)
                self._sleep(wait)
        raise GroqError(f"groq call failed after 3 attempts: {last}") from last
