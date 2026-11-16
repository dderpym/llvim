"""std/panels/input/generate.py: /continue queues a cue for the model, which goes in once the turn is over."""

import asyncio

from llvim.core import Request
from llvim.std.conversation import entries
from llvim.std.cues import GENERATE, cued
from llvim.std.panels.input.commands import Context
from llvim.std.panels.input.generate import CONTINUE, cue_the_model


def run(log):
    notices, queued = [], []
    CONTINUE.run(Context(log, notices.append, lambda: None, {"continue": CONTINUE}, queue=lambda *item: queued.append(item)), "")
    return notices, queued


def test_it_queues_a_cue_for_the_model_in_the_bars_queue(fake_log):
    fake_log.say(["assistant"], "one ")
    assert run(fake_log) == ([], [("/continue", cue_the_model)])


def test_it_queues_nothing_when_there_is_nothing_to_continue(fake_log):
    notices, queued = run(fake_log)
    assert "empty" in notices[0] and queued == []


async def test_the_cue_goes_in_after_the_last_message_and_nothing_else(fake_log):
    fake_log.say(["assistant"], "one ")
    await cue_the_model(fake_log)
    assert [e.tags for e in entries(fake_log.read())] == [["assistant"], ["cue", "generate"]]


async def test_the_cue_waits_for_the_turn_in_progress_to_end(fake_log):
    fake_log.say(["user"], "hi")
    fake_log.hold(Request(0, {"provider": "openai"}))
    going_on = asyncio.create_task(cue_the_model(fake_log))
    await asyncio.sleep(0.02)
    assert not going_on.done() and cued(fake_log.read()) is None
    fake_log.say(["assistant"], "hello")
    fake_log.hold(None)
    await asyncio.wait_for(going_on, 1)
    assert cued(fake_log.read()) == GENERATE
