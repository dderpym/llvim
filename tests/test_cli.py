"""cli.py: `llvim` builds one tmux command per project and log, and finds the start script."""

from pathlib import Path

from llvim.cli import CONFIG, command, session_name, start_script, starter


def test_a_session_is_named_per_project_and_log_without_what_tmux_forbids():
    a = Path("/work/app.v2")
    assert session_name(a, "main") == session_name(a, "main")
    assert session_name(a, "main") != session_name(a, "alt")
    assert session_name(a, "main") != session_name(Path("/other/app.v2"), "main")
    assert not set(session_name(a, "feat:x.y")) & set(".:")


def test_the_command_starts_tmux_on_its_own_server_with_the_shipped_config_and_names_the_log(monkeypatch):
    monkeypatch.setenv("LLVIM_SOCKET", "mysock")
    argv = command(Path("/work/app"), "alt")
    assert argv[:5] == ["tmux", "-L", "mysock", "-f", str(CONFIG / "tmux.conf")]
    assert argv[argv.index("-s") + 1] == session_name(Path("/work/app"), "alt")
    assert "LLVIM_PROJECT=/work/app" in argv and "LLVIM_LOG=alt" in argv and argv[-3:-1] == ["llvim-run", "--start"]


def test_the_start_script_is_the_users_python_one_else_their_shell_one_else_the_shipped_one(tmp_path, monkeypatch):
    monkeypatch.setenv("LLVIM_HOME", str(tmp_path))
    assert start_script() == CONFIG / "start.py"
    (tmp_path / "start").write_text("")
    assert start_script() == tmp_path / "start" and starter(tmp_path / "start") == ["sh", str(tmp_path / "start")]
    (tmp_path / "start.py").write_text("")
    assert start_script() == tmp_path / "start.py" and starter(tmp_path / "start.py") == ["llvim-run", "--start", str(tmp_path / "start.py")]
