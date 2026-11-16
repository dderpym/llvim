"""std/env.py: where llvim keeps its settings, which log a program is for, and reading a settings file."""

from pathlib import Path

import pytest

from llvim.std import env


def test_home_is_llvim_home_and_an_empty_one_counts_as_unset(monkeypatch, tmp_path):
    monkeypatch.setenv("LLVIM_HOME", str(tmp_path))
    assert env.home() == tmp_path
    monkeypatch.setenv("LLVIM_HOME", "")
    assert env.home() == Path.home() / ".llvim"


def test_the_log_is_the_one_the_session_names(monkeypatch, tmp_path):
    monkeypatch.setenv("LLVIM_STORE", str(tmp_path / "store"))
    monkeypatch.setenv("LLVIM_PROJECT", str(tmp_path))
    monkeypatch.setenv("LLVIM_LOG", "side")
    log = env.log()
    assert (log.project, log.name) == (tmp_path, "side")


def test_a_settings_file_is_read_and_one_that_is_missing_is_empty(monkeypatch, tmp_path):
    monkeypatch.setenv("LLVIM_HOME", str(tmp_path))
    assert env.settings("x.toml", lambda key, value: None) == {}
    (tmp_path / "x.toml").write_text('a = "b"\n')
    assert env.settings("x.toml", lambda key, value: None) == {"a": "b"}


def test_a_settings_file_that_is_not_toml_or_has_a_wrong_entry_is_an_error_naming_it(monkeypatch, tmp_path):
    monkeypatch.setenv("LLVIM_HOME", str(tmp_path))
    (tmp_path / "x.toml").write_text("not toml")
    with pytest.raises(ValueError, match="x.toml"):
        env.settings("x.toml", lambda key, value: None)
    (tmp_path / "x.toml").write_text("a = 1\n")
    with pytest.raises(ValueError, match="x.toml: a is wrong"):
        env.settings("x.toml", lambda key, value: f"{key} is wrong")
