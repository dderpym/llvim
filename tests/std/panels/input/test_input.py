"""std/panels/input/__init__.py: Input, the program, and `llvim-input`, its command."""

import pytest

import llvim.std.panels.input as input_


def test_the_standard_commands_are_quit_exit_help_and_continue():
    assert [c.name for c in input_.STANDARD] == ["quit", "exit", "help", "continue"]


def test_the_bar_refuses_to_run_off_a_terminal(fake_log, monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    with pytest.raises(SystemExit, match="needs a terminal"):
        input_.Input(log=fake_log).run()


async def test_a_message_the_input_sends_runs_its_hooks(fake_log):
    seen = []

    async def hook(log, writer, text):
        seen.append(text)
        return True

    await input_.Input(log=fake_log, hooks=[hook]).send(fake_log, "hi")
    assert seen == ["hi"]
