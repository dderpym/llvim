"""cli.py: `llvim [log]`, which starts tmux with the shipped config and runs the start script in it."""

import hashlib
import os
import re
import sys
from pathlib import Path

from llvim.std import env

CONFIG = Path(__file__).parent / "config"


def start_script() -> Path:
    """`$LLVIM_HOME/start.py`, else `$LLVIM_HOME/start` (a shell script), else the shipped `start.py`."""
    for name in ("start.py", "start"):
        if (path := env.home() / name).exists():
            return path
    return CONFIG / "start.py"


def session_name(project: Path, log: str) -> str:
    """One tmux session per project and log: readable, unique, and free of the `.` and `:` tmux forbids."""
    key = hashlib.sha1(f"{project}\0{log}".encode()).hexdigest()[:8]
    return re.sub(r"[.:\s]", "_", f"{project.name}-{log}-{key}")


def starter(script: Path) -> list[str]:
    """A Python start script runs through `llvim-run` (see session.py), anything else with `sh`."""
    return ["llvim-run", "--start", str(script)] if script.suffix == ".py" else ["sh", str(script)]


def command(project: Path, log: str = "main") -> list[str]:
    return [
        "tmux", "-L", env.socket(), "-f", str(CONFIG / "tmux.conf"),
        "new-session", "-A", "-s", session_name(project, log), "-c", str(project),
        "-e", f"LLVIM_PROJECT={project}", "-e", f"LLVIM_LOG={log}",
        *starter(start_script()),
    ]  # fmt: skip


def main() -> None:
    argv = command(Path.cwd().resolve(), *sys.argv[1:2])
    try:
        os.execvp(argv[0], argv)
    except FileNotFoundError:
        sys.exit("llvim: tmux not found")
