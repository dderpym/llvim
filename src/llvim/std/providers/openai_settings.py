"""std/providers/openai_settings.py: the provider's settings, from the environment, else `$LLVIM_HOME/openai.toml`, else a
default."""

import json
import os
from pathlib import Path

from llvim.std import env

URL = "https://api.openai.com/v1"
KEYS = ("api_key", "base_url", "model")  # what openai.toml may hold
FILE = "openai.toml"


def settings_file() -> Path:
    return env.home() / FILE


def read() -> dict[str, str]:
    """What ``openai.toml`` holds, or {}. Raises ValueError if it is not valid, or holds a key that other users can read."""
    data = env.settings(FILE, lambda k, v: None if k in KEYS and isinstance(v, str) else f"{k!r} is not a setting; use text values for {', '.join(KEYS)}")
    path = settings_file()
    if data.get("api_key") and path.stat().st_mode & 0o077:
        raise ValueError(f"{path} holds an API key but other users can read it; fix with: chmod 600 {path}")
    return data


def save(settings: dict[str, str]) -> Path:
    """Write ``openai.toml``, readable only by you from the moment it exists. Empty values are left out."""
    path = settings_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(f"{k} = {json.dumps(settings[k])}\n" for k in KEYS if settings.get(k))  # a JSON string is a TOML one
    tmp = path.with_name(path.name + ".tmp")
    tmp.unlink(missing_ok=True)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(body)
    tmp.replace(path)
    return path


def base_url() -> str:
    return os.environ.get("OPENAI_BASE_URL") or read().get("base_url") or URL


def api_key() -> str | None:
    """None (nothing sent) for servers that need no key."""
    return os.environ.get("OPENAI_API_KEY") or read().get("api_key") or None


def model() -> str | None:
    return os.environ.get("LLVIM_MODEL") or read().get("model") or None
