"""std/panels/input/generate.py: /continue leaves a cue for the model and writes nothing else."""

from llvim.core import Request
from llvim.std.cues import GENERATE, cued
from llvim.std.panels.input.commands import Context
from llvim.std.panels.input.generate import CONTINUE


async def run(log):
    notices = []
    await CONTINUE.run(Context(log, notices.append, lambda: None, {"continue": CONTINUE}), "")
    return notices


async def test_it_cues_the_model_after_the_last_message(fake_log):
    fake_log.say(["assistant"], "one ")
    assert await run(fake_log) == [] and cued(fake_log.read()) == GENERATE and len(fake_log.read().messages) == 2


async def test_a_second_continue_adds_no_second_cue(fake_log):
    fake_log.say(["assistant"], "one ")
    await run(fake_log)
    await run(fake_log)
    assert len(fake_log.read().messages) == 2


async def test_it_does_nothing_when_there_is_nothing_to_continue(fake_log):
    assert "empty" in (await run(fake_log))[0] and cued(fake_log.read()) is None


async def test_it_does_not_wait_while_somebody_is_writing(fake_log):
    fake_log.say(["user"], "hi")
    fake_log.hold(Request(0, "provider"))
    assert "busy" in (await run(fake_log))[0] and fake_log.claims[-1].priority >= 0
