"""std/tools/bash/settings.py: the numbers of the bash tool, from the environment, bash.toml, or a default."""

import pytest

from llvim.std.tools.bash.settings import setting


@pytest.fixture(autouse=True)
def clean(tmp_path, monkeypatch):
    for name in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "LLVIM_MODEL", "LLVIM_HOME", "LLVIM_SOCKET"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLVIM_HOME", str(tmp_path / "home"))


def test_a_bash_number_comes_from_the_environment_then_bash_toml_then_the_default(monkeypatch, tmp_path):
    assert setting("max_lines") == 2000
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / "bash.toml").write_text("max_lines = 10\npreview_chars = 0\n")
    assert setting("max_lines") == 10 and setting("preview_chars") == 0
    assert setting("max_bytes") == 50_000 and setting("settle") == 1.5 and setting("user_timeout") == 3600
    monkeypatch.setenv("LLVIM_BASH_MAX_LINES", "20")
    assert setting("max_lines") == 20


def test_a_bad_bash_setting_is_refused_naming_where_it_came_from(monkeypatch, tmp_path):
    monkeypatch.setenv("LLVIM_BASH_MAX_LINES", "lots")
    with pytest.raises(ValueError, match="LLVIM_BASH_MAX_LINES"):
        setting("max_lines")
    monkeypatch.delenv("LLVIM_BASH_MAX_LINES")
    (tmp_path / "home").mkdir()
    for body in ("max_lines = -1\n", 'max_lines = "x"\n', "max_lines = true\n", "nonsense = 1\n", "= broken"):
        (tmp_path / "home" / "bash.toml").write_text(body)
        with pytest.raises(ValueError, match="bash.toml"):
            setting("max_lines")


def test_importing_the_tool_does_not_read_the_settings_so_a_broken_file_fails_only_a_call(tmp_path):
    import subprocess
    import sys

    (tmp_path / "home").mkdir()
    (tmp_path / "home" / "bash.toml").write_text("= broken")
    run = subprocess.run(
        [sys.executable, "-c", "import llvim.std.tools.bash"],
        check=False,
        env={"LLVIM_HOME": str(tmp_path / "home"), "PATH": ""},
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0, run.stderr
