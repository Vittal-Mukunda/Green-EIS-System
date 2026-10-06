"""The API channel with a mocked HTTP transport: no network is ever used."""

from __future__ import annotations

import json

import httpx
import pytest

from gauge.config import ApiParams
from gauge.runner.api import (
    ApiConfigError,
    ApiRunner,
    api_key,
    check_model_listed,
    list_openrouter_models,
)
from gauge.runner.base import RunRequest

PARAMS = ApiParams(temperature=0, max_tokens=500, seed=7, max_retries=3)
REQUEST = RunRequest(
    run_id="B1_C1_r1",
    model="vendor/some-model:free",
    condition="C1",
    repetition=1,
    seed=11,
    prompt="USER TEXT",
    system_prompt="SYSTEM TEXT",
)
GOOD = {
    "model": "vendor/some-model-20260101",
    "choices": [{"message": {"content": '[{"a": 1}]'}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
}


def runner_for(handler, params=PARAMS, sleeps=None, key="sk-test-KEY"):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    sleeps = sleeps if sleeps is not None else []
    return ApiRunner("openrouter", params, key=key, client=client, sleep=sleeps.append), sleeps


def test_request_has_system_and_user_messages_and_only_configured_parameters():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers["authorization"]
        seen["url"] = str(request.url)
        return httpx.Response(200, json=GOOD, headers={"x-ratelimit-remaining": "9", "other": "no"})

    runner, _ = runner_for(handler)
    result = runner.run(REQUEST)
    assert seen["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert seen["auth"] == "Bearer sk-test-KEY"
    assert seen["body"] == {
        "model": "vendor/some-model:free",
        "messages": [
            {"role": "system", "content": "SYSTEM TEXT"},
            {"role": "user", "content": "USER TEXT"},
        ],
        "temperature": 0,
        "max_tokens": 500,
        "seed": 7,
    }  # no top_p: it was not configured, so it is not sent
    assert result.stdout == '[{"a": 1}]' and result.exit_code == 0 and result.stderr == ""
    assert result.cli_version == "openrouter-chat-completions"
    assert result.command == ["POST", "https://openrouter.ai/api/v1/chat/completions"]


def test_everything_rule_12_asks_to_log_is_returned():
    runner, _ = runner_for(
        lambda r: httpx.Response(
            200,
            json=GOOD,
            headers={"x-ratelimit-remaining": "9", "retry-after": "1", "x-other": "n"},
        ),
        params=ApiParams(temperature=0, top_p=0.9, max_tokens=500, seed=7),
    )
    extra = runner.run(REQUEST).extra
    assert extra["temperature"] == 0 and extra["top_p"] == 0.9
    assert extra["max_tokens"] == 500 and extra["api_seed"] == 7
    assert extra["provider_model"] == "vendor/some-model-20260101"  # what the provider returned
    assert (
        extra["response_json"] == GOOD
        and extra["request_json"]["messages"][1]["content"] == "USER TEXT"
    )
    assert extra["rate_limit_headers"] == {"x-ratelimit-remaining": "9", "retry-after": "1"}
    assert "usage_limit" not in extra


def test_the_api_key_is_never_stored_anywhere_in_the_result():
    runner, _ = runner_for(lambda r: httpx.Response(200, json=GOOD), key="sk-SECRET-123")
    result = runner.run(REQUEST)
    dump = json.dumps([result.stdout, result.stderr, result.command, result.extra], default=str)
    assert "sk-SECRET-123" not in dump


def test_unconfigured_parameters_are_omitted_not_defaulted():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=GOOD)

    runner, _ = runner_for(handler, params=ApiParams())
    extra = runner.run(REQUEST).extra
    assert set(seen) == {"model", "messages", "temperature"} and seen["temperature"] == 0
    assert extra["top_p"] is None and extra["max_tokens"] is None and extra["api_seed"] is None


def test_no_system_prompt_sends_one_user_message():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=GOOD)

    runner, _ = runner_for(handler)
    runner.run(RunRequest("r", "m:free", "C1", 1, 1, "only user"))
    assert seen["messages"] == [{"role": "user", "content": "only user"}]


# ---- retries and limits --------------------------------------------------------------------------
def test_429_is_retried_with_backoff_then_succeeds():
    codes = iter([429, 429, 200])

    def handler(request):
        code = next(codes)
        return httpx.Response(code, json=GOOD if code == 200 else {"error": "slow down"})

    runner, sleeps = runner_for(handler)
    result = runner.run(REQUEST)
    assert result.exit_code == 0 and result.stdout and sleeps == [1.0, 2.0]  # 2**0, 2**1
    assert "attempt 1: HTTP 429" in result.stderr and "usage_limit" not in result.extra


def test_retry_after_header_is_honoured_and_capped():
    steps = iter([(429, {"retry-after": "7"}), (429, {"retry-after": "9999"}), (200, {})])

    def handler(request):
        code, headers = next(steps)
        return httpx.Response(code, json=GOOD, headers=headers)

    runner, sleeps = runner_for(handler)
    runner.run(REQUEST)
    assert sleeps == [7.0, 60.0]  # the header, then the 60 s cap


def test_a_persistent_429_is_a_usage_limit_after_all_retries():
    runner, sleeps = runner_for(lambda r: httpx.Response(429, json={"error": "busy"}))
    result = runner.run(REQUEST)
    assert result.exit_code == 429 and result.stdout == "" and result.extra["usage_limit"] is True
    assert len(sleeps) == 3 and "persisted after 4 attempts" in result.stderr


def test_a_daily_limit_message_stops_at_once_without_retrying():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(
            429, json={"error": {"message": "Rate limit exceeded: free-models-per-day"}}
        )

    runner, sleeps = runner_for(handler)
    result = runner.run(REQUEST)
    assert len(calls) == 1 and sleeps == [] and result.extra["usage_limit"] is True
    assert "daily limit" in result.stderr


def test_server_errors_are_retried_and_then_reported_as_failures_not_limits():
    runner, sleeps = runner_for(lambda r: httpx.Response(503, text="unavailable"))
    result = runner.run(REQUEST)
    assert result.exit_code == 503 and "usage_limit" not in result.extra and len(sleeps) == 3


@pytest.mark.parametrize("status", [400, 401, 402, 403, 404])
def test_client_errors_are_not_retried(status):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(status, json={"error": "nope"})

    runner, sleeps = runner_for(handler)
    result = runner.run(REQUEST)
    assert len(calls) == 1 and sleeps == [] and result.exit_code == status
    assert f"HTTP {status}" in result.stderr and "usage_limit" not in result.extra


def test_network_errors_are_retried_then_reported():
    def handler(request):
        raise httpx.ConnectError("no route")

    runner, sleeps = runner_for(handler)
    result = runner.run(REQUEST)
    assert result.exit_code == 1 and len(sleeps) == 3 and "ConnectError" in result.stderr


def test_an_empty_reply_is_recorded_with_its_finish_reason():
    empty = {"model": "m", "choices": [{"message": {"content": None}, "finish_reason": "length"}]}
    runner, _ = runner_for(lambda r: httpx.Response(200, json=empty))
    result = runner.run(REQUEST)
    assert result.exit_code == 0 and result.stdout == ""  # execute_run marks this run failed
    assert "empty reply (finish_reason='length')" in result.stderr


def test_a_malformed_response_body_does_not_crash():
    runner, _ = runner_for(lambda r: httpx.Response(200, text="<html>oops</html>"))
    result = runner.run(REQUEST)
    assert (
        result.stdout == ""
        and "not JSON" in result.stderr
        and result.extra["response_json"] is None
    )


# ---- configuration and model checks --------------------------------------------------------------
def test_unknown_provider_and_unsupported_batch_split_are_refused():
    with pytest.raises(ApiConfigError, match="unknown provider"):
        ApiRunner("nowhere", PARAMS, key="k")
    with pytest.raises(ApiConfigError, match="split_batch_by_sector"):
        ApiRunner("groq", ApiParams(split_batch_by_sector=True), key="k")


def test_the_key_comes_from_the_environment_and_a_missing_key_says_where_to_put_it():
    assert api_key("openrouter", {"OPENROUTER_API_KEY": " k1 "}) == "k1"
    assert api_key("groq", {"GROQ_API_KEY": "k2"}) == "k2"
    with pytest.raises(ApiConfigError, match="OPENROUTER_API_KEY.*\\.env"):
        api_key("openrouter", {})
    with pytest.raises(ApiConfigError):
        api_key("openrouter", {"OPENROUTER_API_KEY": "   "})


MODELS = {"data": [{"id": "a/free-one:free"}, {"id": "b/paid-one"}]}


def listed_client():
    return httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=MODELS)))


def test_the_listing_is_read_without_a_key():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("authorization")
        seen["url"] = str(request.url)
        return httpx.Response(200, json=MODELS)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert list_openrouter_models(client) == {"a/free-one:free", "b/paid-one"}
    assert seen == {"auth": None, "url": "https://openrouter.ai/api/v1/models"}


def test_a_model_must_be_free_and_currently_listed():
    check_model_listed("openrouter", "a/free-one:free", listed_client())
    with pytest.raises(ApiConfigError, match="not in OpenRouter's current model list"):
        check_model_listed("openrouter", "a/gone:free", listed_client())
    with pytest.raises(ApiConfigError, match="must end in ':free'"):
        check_model_listed("openrouter", "b/paid-one", listed_client())
    check_model_listed("groq", "anything", listed_client())  # not checkable without a key


def test_an_unreachable_listing_blocks_the_start():
    def handler(request):
        raise httpx.ConnectError("offline")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(ApiConfigError, match="could not read OpenRouter's model list"):
        check_model_listed("openrouter", "a/free-one:free", client)
