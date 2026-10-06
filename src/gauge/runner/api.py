"""The API channel: the controlled open-weight baseline through a free tier (hard rule 12).

An OpenAI-compatible chat-completions client for OpenRouter (and Groq as the fallback). The
instructions go in the system message and the evidence in the user message, which is exactly the
text the Cursor models receive concatenated. temperature is 0 and logged; top_p, max_tokens and
the seed are sent only if configured and are logged as sent; the full request body (never the key)
and the full response are stored, with the provider-returned model string and rate-limit headers.

Retries use exponential backoff on HTTP 429 and 5xx (Retry-After is honoured). A 429 that persists,
or that names a per-day limit, is reported as a usage limit so the caller can stop cleanly and
resume.
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from gauge.config import ApiParams
from gauge.runner.base import RunRequest, RunResult

BASE_URLS = {
    "openrouter": "https://openrouter.ai/api/v1",
    "groq": "https://api.groq.com/openai/v1",
}
KEY_ENV = {"openrouter": "OPENROUTER_API_KEY", "groq": "GROQ_API_KEY"}
DAILY_LIMIT_RE = re.compile(r"per[- ]day|per day|daily", re.IGNORECASE)
HEADER_PREFIXES = ("x-ratelimit", "retry-after", "x-openrouter")
MAX_BACKOFF_S = 60.0


class ApiConfigError(RuntimeError):
    """The API channel cannot start (no key, model not listed, ...)."""


def api_key(provider: str, environ: dict[str, str] | None = None) -> str:
    env = environ if environ is not None else os.environ
    name = KEY_ENV[provider]
    key = (env.get(name) or "").strip()
    if not key:
        raise ApiConfigError(f"{name} is not set: put it in .env (see .env.example)")
    return key


def list_openrouter_models(client: httpx.Client | None = None) -> set[str]:
    """Model IDs OpenRouter lists right now (a public endpoint: no key needed)."""
    own = client is None
    client = client or httpx.Client(timeout=30)
    try:
        response = client.get(f"{BASE_URLS['openrouter']}/models")
        response.raise_for_status()
        return {m["id"] for m in response.json()["data"]}
    finally:
        if own:
            client.close()


def check_model_listed(provider: str, name: str, client: httpx.Client | None = None) -> None:
    """Refuse a model OpenRouter does not currently list as free (hard rules 4 and 12)."""
    if provider != "openrouter":
        return  # Groq lists models only to key holders; checked at the first call instead
    if not name.endswith(":free"):
        raise ApiConfigError(f"{name}: an OpenRouter model id must end in ':free'")
    try:
        listed = list_openrouter_models(client)
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise ApiConfigError(f"could not read OpenRouter's model list: {exc}") from exc
    if name not in listed:
        raise ApiConfigError(
            f"{name} is not in OpenRouter's current model list; pick another ':free' model "
            "(docs/VERIFY.md V-04)"
        )


class ApiRunner:
    mode = "api"

    def __init__(
        self,
        provider: str,
        params: ApiParams,
        *,
        key: str | None = None,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if provider not in BASE_URLS:
            raise ApiConfigError(f"unknown provider {provider!r}")
        if params.split_batch_by_sector:
            raise ApiConfigError(
                "api.split_batch_by_sector is not implemented (see docs/RUNNER.md)"
            )
        self.provider = provider
        self.params = params
        self._key = key if key is not None else api_key(provider)
        self._client = client or httpx.Client(timeout=params.timeout_seconds)
        self._sleep = sleep
        self.url = f"{BASE_URLS[provider]}/chat/completions"

    # -- request ---------------------------------------------------------------------------------
    def build_body(self, request: RunRequest) -> dict[str, Any]:
        messages = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.append({"role": "user", "content": request.prompt})
        body: dict[str, Any] = {
            "model": request.model,
            "messages": messages,
            "temperature": self.params.temperature,
        }
        if self.params.top_p is not None:
            body["top_p"] = self.params.top_p
        if self.params.max_tokens is not None:
            body["max_tokens"] = self.params.max_tokens
        if self.params.seed is not None:
            body["seed"] = self.params.seed
        return body

    def run(self, request: RunRequest) -> RunResult:
        body = self.build_body(request)
        headers = {"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"}
        started = datetime.now(UTC)
        t0 = time.monotonic()
        notes: list[str] = []
        response: httpx.Response | None = None
        usage_limit = False

        for attempt in range(self.params.max_retries + 1):
            try:
                response = self._client.post(self.url, json=body, headers=headers)
            except httpx.HTTPError as exc:
                notes.append(f"attempt {attempt + 1}: {type(exc).__name__}: {exc}")
                response = None
            else:
                if response.status_code == 429 and DAILY_LIMIT_RE.search(response.text):
                    usage_limit = True
                    notes.append(f"HTTP 429 (daily limit): {response.text[:500]}")
                    break
                if response.status_code != 429 and response.status_code < 500:
                    break
                notes.append(f"attempt {attempt + 1}: HTTP {response.status_code}")
            if attempt < self.params.max_retries:
                self._sleep(self._backoff(attempt, response))
        else:
            if response is not None and response.status_code == 429:
                usage_limit = True
                notes.append(f"HTTP 429 persisted after {self.params.max_retries + 1} attempts")

        return self._result(request, body, response, started, t0, notes, usage_limit)

    def _backoff(self, attempt: int, response: httpx.Response | None) -> float:
        retry_after = response.headers.get("retry-after") if response is not None else None
        try:
            if retry_after is not None:
                return min(MAX_BACKOFF_S, max(0.0, float(retry_after)))
        except ValueError:
            pass
        return min(MAX_BACKOFF_S, 2.0**attempt)

    # -- result ----------------------------------------------------------------------------------
    def _result(self, request, body, response, started, t0, notes, usage_limit) -> RunResult:
        content, parsed, finish = "", None, None
        exit_code = 1
        if response is not None:
            exit_code = 0 if response.status_code == 200 else response.status_code
            try:
                parsed = response.json()
            except ValueError:
                notes.append(
                    f"HTTP {response.status_code}: body is not JSON: {response.text[:500]}"
                )
            if response.status_code == 200 and isinstance(parsed, dict):
                try:
                    choice = parsed["choices"][0]
                    content = choice["message"].get("content") or ""
                    finish = choice.get("finish_reason")
                except (KeyError, IndexError, TypeError):
                    notes.append("response has no choices[0].message")
                if not content.strip():
                    notes.append(f"empty reply (finish_reason={finish!r})")
            elif response.status_code != 200:
                notes.append(f"HTTP {response.status_code}: {response.text[:500]}")
        headers = (
            {k: v for k, v in response.headers.items() if k.lower().startswith(HEADER_PREFIXES)}
            if response is not None
            else {}
        )
        extra: dict[str, Any] = {
            "temperature": body["temperature"],
            "top_p": body.get("top_p"),
            "max_tokens": body.get("max_tokens"),
            "api_seed": body.get("seed"),
            "provider_model": parsed.get("model") if isinstance(parsed, dict) else None,
            "request_json": body,  # the key is only ever in the header, never here
            "response_json": parsed if isinstance(parsed, dict) else None,
            "rate_limit_headers": headers,
        }
        if usage_limit:
            extra["usage_limit"] = True
        return RunResult(
            stdout=content,
            stderr="\n".join(notes),
            exit_code=exit_code,
            duration_s=round(time.monotonic() - t0, 3),
            command=["POST", self.url],
            cli_version=f"{self.provider}-chat-completions",
            started_utc=started,
            finished_utc=datetime.now(UTC),
            extra=extra,
        )
