"""std/providers/openai_settings.py: the OpenAI provider's settings, from the environment and openai.toml."""

import stat

import pytest

from llvim.std.providers import openai_settings as settings


@pytest.fixture(autouse=True)
def clean(tmp_path, monkeypatch):
    for name in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "LLVIM_MODEL", "LLVIM_HOME", "LLVIM_SOCKET"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLVIM_HOME", str(tmp_path / "home"))


def test_without_a_file_there_are_defaults():
    assert settings.read() == {}
    assert (settings.base_url(), settings.api_key(), settings.model()) == (settings.URL, None, None)


def test_the_file_fills_in_what_the_environment_does_not_and_the_environment_wins(monkeypatch):
    settings.save({"api_key": "sk-file", "base_url": "http://file/v1", "model": "file-model"})
    assert (settings.api_key(), settings.base_url(), settings.model()) == ("sk-file", "http://file/v1", "file-model")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://env/v1")
    monkeypatch.setenv("LLVIM_MODEL", "env-model")
    assert (settings.api_key(), settings.base_url(), settings.model()) == ("sk-env", "http://env/v1", "env-model")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    assert settings.api_key() == "sk-file"  # empty is unset


def test_saving_is_private_from_the_start_and_round_trips_awkward_text():
    given = {"api_key": 'sk-"quoted"\\ and ünï', "base_url": "http://localhost:11434/v1", "model": "", "other": "ignored"}
    path = settings.save(given)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert settings.read() == {"api_key": given["api_key"], "base_url": "http://localhost:11434/v1"}  # empty and unknown left out
    assert [p.name for p in path.parent.iterdir()] == ["openai.toml"]  # no temporary file left behind


def test_a_key_that_others_can_read_is_refused_but_a_file_without_one_is_fine():
    path = settings.save({"api_key": "sk-x"})
    path.chmod(0o644)
    with pytest.raises(ValueError, match=f"chmod 600 {path}"):
        settings.api_key()
    settings.save({"base_url": "http://x/v1"}).chmod(0o644)
    assert settings.base_url() == "http://x/v1"


def test_a_file_that_is_not_settings_is_refused_with_its_name():
    path = settings.settings_file()
    path.parent.mkdir(parents=True)
    for text in ("api_key = ", 'colour = "red"\n'):
        path.write_text(text)
        path.chmod(0o600)
        with pytest.raises(ValueError, match="openai.toml"):
            settings.read()
