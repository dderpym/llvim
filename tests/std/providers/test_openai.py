"""std/providers/openai.py: a provider for OpenAI-compatible APIs. The log is a stub; the endpoint is a fake one."""

import asyncio
import threading

import pytest

from llvim.core import Request
from llvim.std.conversation import entries
from llvim.std.providers import openai
from llvim.std.tools import Tool


async def respond(log, url, **kw):
    return await openai.respond(log, "m", url, **kw)


def said(log):
    return [(e.tags, e.content) for e in entries(log.read())]


# --- what is sent ---


def test_the_messages_with_a_role_are_sent_and_the_rest_are_left_out(entry):
    sent = openai.chat([
        entry(["system"], "be brief"), entry(["user"], "hi"), entry(["cue", "generate"]), entry(["error"], "500"),
        entry(["assistant"], "hello"),
    ])  # fmt: skip
    assert sent == [
        {"role": "system", "content": "be brief"}, {"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}
    ]  # fmt: skip


def test_reasoning_goes_back_on_the_assistant_message_after_it_only_for_the_turn_in_progress(entry):
    sent = openai.chat([
        entry(["user"], "one"), entry(["thinking"], "old"), entry(["assistant"], "a"),
        entry(["user"], "two"), entry(["thinking"], "new "), entry(["thinking"], "more"), entry(["assistant"], "b"),
    ])  # fmt: skip
    assert [m.get("reasoning_content") for m in sent] == [None, None, None, "new more"]


def test_reasoning_before_something_other_than_an_answer_is_not_sent(entry):
    sent = openai.chat([entry(["user"], "one"), entry(["thinking"], "lost"), entry(["user"], "two"), entry(["assistant"], "a")])
    assert "reasoning_content" not in sent[-1]


def test_calls_go_back_on_the_assistant_message_each_followed_by_its_result_wherever_the_result_is(entry):
    sent = openai.chat([
        entry(["user"], "look"), entry(["thinking"], "hm"), entry(["assistant"], "I'll look."),
        entry(["tool_call", "bash"], '{"command": "ls"}', call_id="a"), entry(["tool_call", "bash"], "", call_id="b"),
        entry(["cue", "tools"]), entry(["tool_start", "bash"], call_id="a"), entry(["tool_result", "bash"], "a.txt", call_id="a"),
        entry(["tool_result", "bash"], "b.txt", call_id="b"), entry(["assistant"], "Two files."),
    ])  # fmt: skip
    assert sent == [
        {"role": "user", "content": "look"},
        {"role": "assistant", "content": "I'll look.", "reasoning_content": "hm", "tool_calls": [
            {"id": "a", "type": "function", "function": {"name": "bash", "arguments": '{"command": "ls"}'}},
            {"id": "b", "type": "function", "function": {"name": "bash", "arguments": "{}"}},
        ]},
        {"role": "tool", "tool_call_id": "a", "content": "a.txt"},
        {"role": "tool", "tool_call_id": "b", "content": "b.txt"},
        {"role": "assistant", "content": "Two files."},
    ]  # fmt: skip


def test_a_call_with_no_result_is_still_answered_so_the_api_accepts_the_conversation(entry):
    sent = openai.chat([entry(["user"], "go"), entry(["tool_call", "bash"], "{}", call_id="a"), entry(["user", "stop"], "stopped")])
    assert sent[1]["content"] is None and sent[2] == {"role": "tool", "tool_call_id": "a", "content": openai.NO_RESULT}
    assert sent[3]["role"] == "user"


def test_a_call_cut_off_while_its_arguments_streamed_is_not_sent(entry):
    sent = openai.chat([
        entry(["user"], "go"), entry(["thinking"], "hm"), entry(["tool_call", "bash"], '{"command": "l', call_id="a"),
        entry(["tool_result", "bash"], "stray", call_id="a"), entry(["user", "stop"], "stopped"), entry(["assistant"], "ok"),
    ])  # fmt: skip
    assert sent == [
        {"role": "user", "content": "go"}, {"role": "user", "content": "stopped"}, {"role": "assistant", "content": "ok"}
    ]  # fmt: skip


def test_a_call_the_user_made_is_told_to_the_model_as_their_message_once_it_has_a_result(entry):
    mine = entry(["tool_call", "bash"], '{"command": "make", "interactive": true}', call_id="u", user=True)
    assert openai.chat([mine]) == []
    sent = openai.chat([mine, entry(["tool_result", "bash"], "built", call_id="u", user=True)])
    assert sent == [{"role": "user", "content": "I ran this in a terminal:\n$ make\nbuilt"}]


# --- answering ---


async def test_a_cued_log_is_answered_by_a_streamed_assistant_message_with_the_model_and_committed(fake_log, endpoint):
    server = endpoint("Hel", "lo")
    fake_log.ask("hi")
    assert await respond(fake_log, server.url, api_key="sk-test") is True
    (reply,) = entries(fake_log.read())[2:]
    assert (reply.tags, reply.content, reply.extra, reply.uncommitted) == (["assistant"], "Hello", {"model": "m"}, False)
    assert fake_log.authors[-1].name == "m" and fake_log.claims[-1] == Request(0, {"provider": "openai", "model": "m"})
    (request,) = server.requests
    assert request["path"] == "/v1/chat/completions" and request["auth"] == "Bearer sk-test"
    assert request["body"] == {"model": "m", "messages": [{"role": "user", "content": "hi"}], "stream": True}


async def test_only_a_cue_for_the_model_as_the_last_message_is_answered(fake_log, endpoint):
    server = endpoint("x")
    assert await respond(fake_log, server.url) is False  # an empty log
    fake_log.say(["user"], "hi")
    assert await respond(fake_log, server.url) is False  # nobody cued it
    fake_log.say(["cue", "tools"])
    assert await respond(fake_log, server.url) is False  # a cue for someone else
    assert server.requests == []


async def test_reasoning_becomes_a_thinking_message_before_the_answer(fake_log, endpoint):
    server = endpoint(("reasoning_content", "Let me "), ("reasoning", "think."), "Hi", " there")
    fake_log.ask("hello")
    await respond(fake_log, server.url)
    assert said(fake_log)[2:] == [(["thinking"], "Let me think."), (["assistant"], "Hi there")]


async def test_the_tools_are_offered_and_a_streamed_call_is_a_message_of_its_own_followed_by_a_cue_for_the_runner(fake_log, endpoint):
    first = [{"index": 0, "id": "call_1", "function": {"name": "bash", "arguments": '{"comm'}}]
    rest = [{"index": 0, "function": {"arguments": 'and": "ls"}'}}]
    server = endpoint("Looking.", ("tool_calls", first), ("tool_calls", rest))
    fake_log.ask("list")
    bash = Tool("bash", "Run it.", {"type": "object"}, lambda a, c: "")
    await respond(fake_log, server.url, tools=[bash])
    assert server.requests[0]["body"]["tools"] == [
        {"type": "function", "function": {"name": "bash", "description": "Run it.", "parameters": {"type": "object"}}}
    ]
    assert said(fake_log)[2:] == [
        (["assistant"], "Looking."), (["tool_call", "bash"], '{"command": "ls"}'), (["cue", "tools"], "")
    ]  # fmt: skip
    assert entries(fake_log.read())[3].extra == {"model": "m", "call_id": "call_1"}


async def test_the_model_is_sent_the_log_as_the_context_renderers_leave_it(fake_log, endpoint):
    server = endpoint("ok")
    fake_log.say(["user"], "secret")
    fake_log.ask("hello")
    await respond(fake_log, server.url, context=[lambda log: [e for e in log if e.content != "secret"]])
    assert server.requests[0]["body"]["messages"] == [{"role": "user", "content": "hello"}]


async def test_with_no_tools_none_are_offered_and_a_reply_without_calls_cues_nobody(fake_log, endpoint):
    server = endpoint("hi")
    fake_log.ask("hello")
    await respond(fake_log, server.url)
    assert "tools" not in server.requests[0]["body"] and said(fake_log)[-1] == (["assistant"], "hi")


async def test_a_call_cut_short_by_someone_of_higher_priority_is_not_sent_to_the_runner(fake_log, endpoint):
    resume = threading.Event()
    call = [{"index": 0, "id": "c", "function": {"name": "bash", "arguments": "{"}}]
    server = endpoint(("tool_calls", call), resume, "more")
    fake_log.ask("go")
    answering = asyncio.create_task(respond(fake_log, server.url))
    while len(said(fake_log)) < 3:
        await asyncio.sleep(0.005)
    fake_log.waiting = [Request(5)]
    try:
        await asyncio.wait_for(answering, 1)
    finally:
        resume.set()
    assert said(fake_log)[-1] == (["tool_call", "bash"], "{")


# --- when it goes wrong ---


async def test_a_failed_connection_is_tried_again_and_the_wait_never_reaches_a_commit(fake_log, endpoint):
    server = endpoint("Hello", status=[503, 429, 200])
    fake_log.ask("hi")
    await respond(fake_log, server.url, backoff=0.01)
    assert len(server.requests) == 3 and said(fake_log)[2:] == [(["assistant"], "Hello")]


async def test_a_refusal_that_cannot_improve_is_written_as_an_error_once_and_never_leaks_the_key(fake_log, endpoint):
    server = endpoint(status=401)
    fake_log.ask("hi")
    await respond(fake_log, server.url, api_key="sk-secret", backoff=0.01)
    tags, content = said(fake_log)[-1]
    assert len(server.requests) == 1 and tags == ["error"] and "401" in content and "sk-secret" not in content
    assert await respond(fake_log, server.url) is False  # the error overtook the cue: it does not try again by itself


async def test_a_stream_in_a_shape_it_does_not_know_is_an_error_in_the_log_not_a_dead_provider(fake_log, endpoint):
    server = endpoint(b'data: {"choices": ["not an object"]}\n\n')
    fake_log.ask("hi")
    assert await respond(fake_log, server.url, retries=0) is True
    assert said(fake_log)[-1][0] == ["error"] and "not a chat stream" in said(fake_log)[-1][1]


async def test_text_that_already_arrived_is_kept_and_not_started_over_when_the_stream_breaks(fake_log, endpoint):
    server = endpoint("part", b"data: {not json\n\n")
    fake_log.ask("hi")
    await respond(fake_log, server.url, retries=3, backoff=0.01)
    assert len(server.requests) == 1 and said(fake_log)[2] == (["assistant"], "part") and said(fake_log)[-1][0] == ["error"]


# --- handing over ---


async def test_someone_of_higher_priority_already_waiting_gets_the_log_with_nothing_written(fake_log, endpoint):
    server = endpoint("one ", "two ")
    fake_log.ask("hi")
    fake_log.waiting = [Request(5)]
    assert await respond(fake_log, server.url) is False
    assert said(fake_log)[-1] == (["cue", "generate"], "") and fake_log.holder() is None


async def test_it_stops_where_it_is_and_commits_what_arrived_even_while_the_server_is_silent(fake_log, endpoint):
    resume = threading.Event()
    server = endpoint("one ", resume, "two")
    fake_log.ask("hi")
    answering = asyncio.create_task(respond(fake_log, server.url))
    while len(said(fake_log)) < 3:
        await asyncio.sleep(0.005)
    fake_log.waiting = [Request(5)]
    try:
        await asyncio.wait_for(answering, 1)
    finally:
        resume.set()
    assert said(fake_log)[2:] == [(["assistant"], "one ")]


async def test_waiting_to_reconnect_says_so_and_hands_over_with_nothing_written(fake_log, endpoint):
    server = endpoint(status=503)
    fake_log.ask("hi")
    answering = asyncio.create_task(respond(fake_log, server.url, backoff=10))
    while said(fake_log)[-1][0] != ["status"]:
        await asyncio.sleep(0.005)
    fake_log.waiting = [Request(5)]
    assert await asyncio.wait_for(answering, 1) is False
    assert said(fake_log)[-1] == (["cue", "generate"], "") and len(fake_log.read().messages) == 2


# --- the program ---


async def test_serving_answers_each_cue_as_it_comes(fake_log, endpoint):
    server = endpoint("first", then=[["second"]])
    serving = asyncio.create_task(openai.serve(fake_log, "m", server.url, None, 5, 0, 0))
    for question in ("a", "b"):
        fake_log.ask(question)
        while said(fake_log)[-1][0] != ["assistant"] or fake_log.holder():
            await asyncio.sleep(0.005)
    serving.cancel()
    await asyncio.gather(serving, return_exceptions=True)
    assert [content for tags, content in said(fake_log) if tags == ["assistant"]] == ["first", "second"]


def test_the_command_answers_once_with_the_settings_it_finds_and_needs_a_model(fake_log, endpoint, monkeypatch, tmp_path):
    from llvim.std.providers import openai_settings

    for name in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "LLVIM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLVIM_HOME", str(tmp_path))
    monkeypatch.setattr(openai, "Log", lambda *a, **k: fake_log)
    with pytest.raises(SystemExit, match="no model"):
        openai.main(["--once"])
    server = endpoint("from the file")
    openai_settings.save({"api_key": "sk-file", "base_url": server.url, "model": "file-model"})
    fake_log.ask("hello")
    openai.main(["--once"])
    assert said(fake_log)[-1] == (["assistant"], "from the file") and entries(fake_log.read())[-1].extra == {"model": "file-model"}
    assert server.requests[0]["auth"] == "Bearer sk-file" and server.requests[0]["body"]["model"] == "file-model"


# --- TLS ---


def test_with_no_root_certificate_trusted_by_default_it_trusts_the_first_system_bundle_there_is(monkeypatch, tmp_path):
    import os
    import ssl

    real = next((bundle for bundle in openai.BUNDLES if os.path.isfile(bundle)), None)
    if real is None:
        pytest.skip("no system CA bundle here")
    monkeypatch.setattr(openai.ssl, "create_default_context", lambda: ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT))
    monkeypatch.setattr(openai, "BUNDLES", (str(tmp_path / "missing.crt"), real))
    monkeypatch.delenv("NIX_SSL_CERT_FILE", raising=False)
    openai.tls.cache_clear()
    try:
        assert openai.tls().cert_store_stats()["x509_ca"] > 0
    finally:
        openai.tls.cache_clear()


async def test_a_certificate_it_cannot_trust_is_an_error_at_once_that_says_what_to_do(fake_log, monkeypatch):
    import ssl
    import urllib.error

    tries = []

    def refuse(*args, **kwargs):
        tries.append(1)
        raise urllib.error.URLError(ssl.SSLCertVerificationError(1, "certificate verify failed"))

    monkeypatch.setattr(openai.urllib.request, "urlopen", refuse)
    fake_log.ask("hi")
    await respond(fake_log, "https://example.invalid/v1", backoff=0.01)
    tags, content = said(fake_log)[-1]
    assert tries == [1] and tags == ["error"] and "SSL_CERT_FILE" in content
