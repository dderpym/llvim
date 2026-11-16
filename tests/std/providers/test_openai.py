"""std/providers/openai.py: a provider for OpenAI-compatible APIs. The log is a stub; the endpoint is a fake one."""

import asyncio
import threading

import pytest

from llvim.core import Request
from llvim.std.conversation import entries
from llvim.std.providers import openai


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
