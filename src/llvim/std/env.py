"""std/env.py: where llvim keeps its settings, its tmux server, which log a program is for, and reading a settings file."""

import os
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

from llvim.core import Log


def home() -> Path:
    """`$LLVIM_HOME`, else `~/.llvim`. An empty value counts as unset."""
    return Path(os.environ.get("LLVIM_HOME") or Path.home() / ".llvim")


def socket() -> str:
    """`$LLVIM_SOCKET`, the name of llvim's tmux server, else `llvim`."""
    return os.environ.get("LLVIM_SOCKET") or "llvim"


def log() -> Log:
    """`$LLVIM_LOG` (default `main`) of `$LLVIM_PROJECT` (default the working folder)."""
    return Log(os.environ.get("LLVIM_PROJECT") or ".", os.environ.get("LLVIM_LOG") or "main")


def settings(file: str, problem: Callable[[str, Any], str | None]) -> dict[str, Any]:
    """What `home()/file` holds, or {} without one. `problem(key, value)` says what is wrong with an entry, or None.
    ValueError naming the file if it is not TOML or an entry has a problem."""
    path = home() / file
    try:
        data = tomllib.loads(path.read_text())
    except FileNotFoundError:
        return {}
    except tomllib.TOMLDecodeError as error:
        raise ValueError(f"{path}: {error}") from None
    for key, value in data.items():
        if wrong := problem(key, value):
            raise ValueError(f"{path}: {wrong}")
    return data
