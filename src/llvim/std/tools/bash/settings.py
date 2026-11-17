"""std/tools/bash/settings.py: the bash tool's numbers: `$LLVIM_BASH_<NAME>`, else `<name>` in `$LLVIM_HOME/bash.toml`, else the
default. Read when a call runs, so a broken `bash.toml` fails a call, not every program that loads the tools."""

import os

from llvim.std import env

DEFAULTS = {
    "timeout": 120.0,  # seconds before a command is stopped
    "max_lines": 2000,  # the most output the model is given; more is saved to a file instead
    "max_bytes": 50_000,
    "long_line_bytes": 10_000,  # a line at least this long is pointed out (0: none is), by number, so the model does not grep it blind
    "long_line_count": 5,  # how many of them are numbered
    "preview_chars": 500,  # of that file, half from its start and half from its end, so the model knows what it is
}


def _problem(key: str, value: object) -> str | None:
    if key not in DEFAULTS:
        return f"{key!r} is not a setting; use numbers for {', '.join(DEFAULTS)}"
    try:
        ok = not isinstance(value, bool) and isinstance(value, (int, float, str)) and float(value) >= 0
    except ValueError:
        ok = False
    return (
        None if ok else f"{key} must be a number that is not negative, not {value!r}"
    )  # (0 is allowed: it turns a preview off)


def setting(name: str) -> float:
    """One number. Raises ValueError, naming where it came from, if it is not a number or is negative."""
    if name not in DEFAULTS:
        raise KeyError(name)
    var = f"LLVIM_BASH_{name.upper()}"
    if value := os.environ.get(var):
        if wrong := _problem(name, value):
            raise ValueError(f"{var}: {wrong}")
        return float(value)
    return float(env.settings("bash.toml", _problem).get(name, DEFAULTS[name]))
