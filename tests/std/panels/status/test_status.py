"""std/panels/status/__init__.py: Status, the program, and `llvim-status`, its command."""

import pytest

import llvim.std.panels.status as status


def test_the_built_in_renderers_are_activity_then_model():
    assert status.BUILTIN == [status.activity, status.model]


def test_the_status_bar_refuses_to_run_off_a_terminal(fake_log):
    with pytest.raises(SystemExit, match="needs a terminal"):
        status.Status(log=fake_log).run()
