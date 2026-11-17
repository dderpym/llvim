"""std/tools/bash/command.py: /bash puts a terminal of the user's in the log, cues the runner, and moves the keyboard to it."""

import asyncio
import json

from llvim.std.conversation import entries
from llvim.std.panels.input.commands import Context
from llvim.std.tools import bash


async def run(fake_log, layout, arg):
    """`/bash arg`, through a queue that runs the work at once."""
    panes, tmux = layout(viewer="%2")
    queued, notices = [], []
    context = Context(
        fake_log, notices.append, lambda: None, {"bash": bash.COMMAND}, panes, lambda label, work: queued.append(work)
    )
    bash.COMMAND.run(context, arg)
    for work in queued:
        await work(fake_log)
    return tmux, notices


def test_it_is_the_command_bash_for_an_input_bar_to_be_given():
    assert bash.COMMAND.name == "bash"


async def test_the_call_is_the_users_and_interactive_and_the_runner_is_cued(fake_log, layout):
    await run(fake_log, layout, "htop")
    call, cue = entries(fake_log.read())
    assert call.tags == ["tool_call", "bash"] and json.loads(call.content) == {"command": "htop", "interactive": True}
    assert call.extra["user"] is True and call.extra["call_id"].startswith("user_") and cue.tags == ["cue", "tools"]
    assert not fake_log.read().uncommitted


async def test_with_no_command_it_is_a_shell(fake_log, layout):
    await run(fake_log, layout, "")
    assert json.loads(entries(fake_log.read())[0].content)["command"] == "bash"


async def test_once_the_call_is_in_the_log_the_focus_moves_to_the_viewer(fake_log, layout):
    tmux, _ = await run(fake_log, layout, "ls")
    assert tmux.focused == ["%2"]


async def test_it_waits_for_the_turn_like_a_message(fake_log, layout):
    fake_log.ask("hi")  # the model has a cue it has not answered
    pending = asyncio.ensure_future(run(fake_log, layout, "ls"))
    await asyncio.sleep(0.02)
    assert not pending.done() and len(entries(fake_log.read())) == 2
    fake_log.say(["assistant"], "hello")
    await pending
    assert entries(fake_log.read())[-2].tags == ["tool_call", "bash"]
