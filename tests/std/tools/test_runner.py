"""std/tools/runner.py: the runner answers the tool calls a provider left in the log. The log is a stub; the tools are made here."""

import asyncio

from llvim.core import Request
from llvim.std.conversation import entries
from llvim.std.tools import Registry, Tool
from llvim.std.tools.runner import CUT_OFF, NOTHING, REQUEST, STOPPED, recover, respond

ANY = {"type": "object"}


def said(log):
    return [(e.tags, e.content) for e in entries(log.read())]


def ask(log, *ids, user=False):
    """A turn that made calls of `echo`, one per id, and the cue for the runner."""
    for id in ids:
        log.say(["tool_call", "echo"], f'{{"text": "{id}"}}', call_id=id, **({"user": True} if user else {}))
    log.say(["cue", "tools"])


async def echo(arguments, ctx):
    return arguments.get("text", "")


ECHO = Registry([Tool("echo", "Say it back.", ANY, echo)])


async def test_a_cued_call_is_started_run_answered_and_the_model_is_cued_after_it(fake_log):
    ask(fake_log, "a")
    assert await respond(fake_log, ECHO) == 1
    assert said(fake_log)[2:] == [
        (["tool_start", "echo"], ""),
        (["tool_result", "echo"], "a"),
        (["cue", "generate"], ""),
    ]
    result = entries(fake_log.read())[3]
    assert result.extra == {"call_id": "a", "error": False} and not result.uncommitted
    assert fake_log.claims == [REQUEST] and fake_log.authors[-1].name == "llvim-tools"


async def test_the_start_is_committed_before_the_tool_runs(fake_log):
    seen = []

    async def look(arguments, ctx):
        snapshot = ctx.log.read()
        seen.append((entries(snapshot)[-1].tags, snapshot.uncommitted))
        return ""

    ask(fake_log, "a")
    await respond(fake_log, Registry([Tool("echo", "x", ANY, look)]))
    assert seen == [(["tool_start", "echo"], ())]


async def test_calls_run_one_at_a_time_oldest_first_and_only_the_last_result_is_followed_by_the_cue(fake_log):
    ask(fake_log, "a", "b")
    assert await respond(fake_log, ECHO) == 2
    assert [tags[0] for tags, _ in said(fake_log)[3:]] == [
        "tool_start",
        "tool_result",
        "tool_start",
        "tool_result",
        "cue",
    ]


async def test_the_tool_gets_the_call_the_project_folder_the_log_and_the_held_writer(fake_log):
    got = {}

    async def look(arguments, ctx):
        got.update(call=ctx.call.extra["call_id"], cwd=ctx.cwd, log=ctx.log, writable=ctx.writer is not None)
        return ""

    ask(fake_log, "a")
    await respond(fake_log, Registry([Tool("echo", "x", ANY, look)]))
    assert got == {"call": "a", "cwd": fake_log.project, "log": fake_log, "writable": True}


async def test_only_a_cue_for_the_tools_as_the_last_message_is_answered(fake_log):
    assert await respond(fake_log, ECHO) == 0
    fake_log.say(["tool_call", "echo"], "{}", call_id="a")
    assert await respond(fake_log, ECHO) == 0  # nobody cued it
    assert fake_log.claims == []


async def test_after_calls_the_user_made_the_model_is_not_cued(fake_log):
    ask(fake_log, "mine", user=True)
    await respond(fake_log, ECHO)
    assert said(fake_log)[-1][0] == ["tool_result", "echo"]
    assert entries(fake_log.read())[-1].extra["user"] is True


async def test_a_failing_call_is_answered_with_its_error_and_the_turn_goes_on(fake_log):
    ask(fake_log, "a")
    await respond(fake_log, Registry([Tool("echo", "x", {"type": "object", "required": ["nope"]}, echo)]))
    result = entries(fake_log.read())[3]
    assert result.extra["error"] is True and "'nope' is required" in result.content
    assert said(fake_log)[-1] == (["cue", "generate"], "")


async def test_outranked_while_a_call_runs_the_tool_is_cancelled_the_rest_are_left_and_nobody_is_cued(fake_log):
    async def stopped(arguments, ctx):
        fake_log.waiting.append(Request(100, "stop"))
        await asyncio.sleep(30)

    ask(fake_log, "a", "b")
    assert await respond(fake_log, Registry([Tool("echo", "x", ANY, stopped)])) == 1
    assert said(fake_log)[3:] == [(["tool_start", "echo"], ""), (["tool_result", "echo"], STOPPED)]
    assert not fake_log.read().uncommitted and fake_log.holder() is None


async def test_an_async_tool_that_answers_its_cancel_has_its_answer_kept(fake_log):
    async def stopped(arguments, ctx):
        fake_log.waiting.append(Request(100, "stop"))
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            return "printed so far"

    ask(fake_log, "a")
    await respond(fake_log, Registry([Tool("echo", "x", ANY, stopped)]))
    assert said(fake_log)[-1] == (["tool_result", "echo"], "printed so far")


async def test_outranked_a_sync_tool_is_told_to_stop_and_its_answer_is_the_result(fake_log):
    def stopped(arguments, ctx):
        fake_log.waiting.append(Request(100, "stop"))
        return "stopped" if ctx.cancelled.wait(5) else "ran out"

    ask(fake_log, "a")
    await respond(fake_log, Registry([Tool("echo", "x", ANY, stopped)]))
    assert said(fake_log)[-1] == (["tool_result", "echo"], "stopped")


async def test_a_message_waiting_at_the_same_priority_does_not_stop_a_tool(fake_log):
    async def patient(arguments, ctx):
        fake_log.waiting.append(Request(0, "a message"))
        await asyncio.sleep(0.05)
        return "done"

    ask(fake_log, "a")
    await respond(fake_log, Registry([Tool("echo", "x", ANY, patient)]))
    assert said(fake_log)[-2:] == [(["tool_result", "echo"], "done"), (["cue", "generate"], "")]


async def test_a_call_a_dead_runner_left_is_answered_as_interrupted_not_run_again_and_the_turn_goes_on(fake_log):
    ran = []

    async def count(arguments, ctx):
        ran.append(ctx.call.extra["call_id"])
        return ""

    fake_log.say(["tool_call", "echo"], "{}", call_id="a")
    fake_log.say(["tool_call", "echo"], "{}", call_id="b")
    fake_log.say(["tool_start", "echo"], "", call_id="a")
    assert await recover(fake_log, Registry([Tool("echo", "x", ANY, count)])) == 2
    assert ran == ["b"]
    assert said(fake_log)[3] == (["tool_result", "echo"], CUT_OFF) and said(fake_log)[-1] == (["cue", "generate"], "")


async def test_with_nothing_cut_off_recovering_does_nothing(fake_log):
    ask(fake_log, "a")
    assert await recover(fake_log, ECHO) == 0 and fake_log.claims == []


async def test_a_cue_with_no_call_waiting_is_overtaken_by_an_error_so_the_turn_ends(fake_log):
    fake_log.say(["user"], "hi")
    fake_log.say(["cue", "tools"])
    assert await respond(fake_log, ECHO) == 0
    assert said(fake_log)[-1] == (["error"], NOTHING)
