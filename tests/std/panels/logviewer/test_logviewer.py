"""std/panels/logviewer/__init__.py: Viewer, the program, and `logviewer`, its command."""

import llvim.std.panels.logviewer as logviewer


def test_off_a_terminal_the_viewer_prints_the_log_as_plain_text(fake_log, capsys):
    fake_log.say(["note"], "hello")
    logviewer.Viewer(log=fake_log, once=True).run()
    assert "hello" in capsys.readouterr().out


def test_the_command_shows_the_log_it_is_given_in_the_project_it_is_given(fake_log, capsys, monkeypatch):
    opened = []
    monkeypatch.setattr(logviewer, "Log", lambda project, name: opened.append((project, name)) or fake_log)
    fake_log.say(["note"], "hello")
    logviewer.main(["other", "-p", "/somewhere", "--once"])
    assert opened == [("/somewhere", "other")] and "hello" in capsys.readouterr().out
