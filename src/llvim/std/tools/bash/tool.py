"""std/tools/bash/tool.py: TOOL, the bash tool: run a shell command in the project folder, in a terminal the user watches, and
return what it printed, shaped for the model."""

import os
import signal
import statistics
import tempfile
import time

from llvim.std.tmux import TmuxError
from llvim.std.tools.bash import terminal
from llvim.std.tools.bash.settings import setting
from llvim.std.tools.calls import call_id
from llvim.std.tools.registry import Context, Tool, ToolError

PARAMETERS = {
    "type": "object",
    "properties": {
        "command": {"type": "string", "description": "The bash command to run."},
        "timeout": {
            "type": "number",
            "description": "Seconds to wait before stopping it. Leave it out for the default, which the user sets.",
        },
        "interactive": {
            "type": "boolean",
            "description": "This makes the command interactive to stdin. ONLY use this for when you want the user to interact with something, like a sudo prompt. This does not make it interactive for you.",
        },
    },
    "required": ["command"],
}


def size(n: int) -> str:
    return f"{n} B" if n < 1024 else f"{n / 1024:.0f} KB" if n < 1024**2 else f"{n / 1024**2:.1f} MB"


def plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def count(text: str) -> int:
    """How many lines the text has (a line is what a newline ends)."""
    return text.count("\n") + (1 if text and not text.endswith("\n") else 0)


def shape(text: str) -> str:
    """What the lines are like: how many are long (and which), and the median, so the model knows what grep will print."""
    sizes = [len(line.encode()) for line in text.split("\n")]
    out = f"median line {size(int(statistics.median_low(sizes)))}"
    floor = setting("long_line_bytes")
    long = [n for n, b in enumerate(sizes, 1) if floor and b >= floor]
    if long:
        shown = ", ".join(map(str, long[: int(setting("long_line_count"))]))
        more = (
            f", +{len(long) - int(setting('long_line_count'))} more" if len(long) > setting("long_line_count") else ""
        )
        out = (
            f"{plural(len(long), 'line')} >= {size(int(floor))} ({'line' if len(long) == 1 else 'lines'} {shown}{more}); "
            + out
        )
    return out


def excerpt(lines: list[str], budget: int, end: bool = False) -> str:
    """Whole lines from the start (or the end) that fit in ``budget`` characters, so no line in a preview is a fragment. A first
    line longer than all of it is cut, and says so, so it is not taken for a short line."""
    order = range(len(lines) - 1, -1, -1) if end else range(len(lines))
    taken, used = [], 0
    for n in order:
        if used + len(lines[n]) > budget:
            break
        taken.append(n)
        used += len(lines[n]) + 1
    if taken:
        return "\n".join(lines[n] for n in sorted(taken))
    n = order[0]
    label = f"…(line {n + 1}, {size(len(lines[n].encode()))}, excerpt mid-line)…"
    return label + lines[n][-budget:] if end else lines[n][:budget] + label


def spill(text: str, seconds: float | None = None) -> str:
    """Save the output to a file only its owner can read (it may hold secrets) and say what the model should do about it."""
    fd, path = tempfile.mkstemp(prefix="llvim-out-", suffix=".log")
    with os.fdopen(fd, "w") as f:
        f.write(text)
    note = (
        "Output too large, please parse in chunks with grep and sed! Do not cat the whole file again.\n"
        f"Sent to {path}\n{size(len(text.encode()))}, {plural(count(text), 'line')}{took(seconds, ', ran ')}\n{shape(text)}"
    )
    half = int(setting("preview_chars")) // 2
    if half and len(text) > 2 * half:
        lines = text.split("\n")
        note += f"\nStart:\n{excerpt(lines, half)}\n[...]\nEnd:\n{excerpt(lines, half, end=True)}"
    return note


def took(seconds: float | None, before: str) -> str:
    return "" if seconds is None else f"{before}{seconds:.1f}s"


def ended(code: int) -> str:
    """An exit code, with the signal it most likely means (a shell reports a program killed by signal N as 128 + N)."""
    try:
        return f"exit code {code} ({signal.Signals(code - 128).name})" if code > 128 else f"exit code {code}"
    except ValueError:
        return f"exit code {code}"


def shown(output: str, seconds: float | None = None) -> str:
    """The output as the model gets it, or the note about the file it was saved to if it is too much."""
    return (
        spill(output, seconds)
        if len(output.encode()) > setting("max_bytes") or count(output) > setting("max_lines")
        else output
    )


def finish(
    output: str,
    code: int | None,
    timeout: float,
    timed_out: bool = False,
    cancelled: bool = False,
    seconds: float | None = None,
) -> str:
    """What the model is told: the output, and how it ended (and, if it did not end well, how long it ran)."""
    output = shown(output, seconds)
    if cancelled:
        raise ToolError(output.rstrip("\n") + f"\n[interrupted{took(seconds, ' after ')}]")
    if timed_out:
        raise ToolError(output.rstrip("\n") + f"\n[timed out after {timeout:g}s and stopped]")
    output = output or "(no output)"
    return output if code == 0 else f"{output.rstrip(chr(10))}\n[{ended(code)}{took(seconds, ' after ')}]"


async def bash(arguments: dict, ctx: Context) -> str:
    timeout = float(arguments.get("timeout") or setting("timeout"))
    started = time.monotonic()
    try:
        ran = await terminal.run(
            arguments["command"],
            ctx.cwd,
            (ctx.call and call_id(ctx.call)) or "",
            timeout,
            bool(arguments.get("interactive")),
        )
    except TmuxError as e:
        raise ToolError(f"bash runs commands in a tmux terminal, and could not get one: {e}") from None
    return finish(ran.output, ran.status, timeout, ran.timed_out, ran.cancelled, time.monotonic() - started)


TOOL = Tool(
    "bash",
    "Run a bash command in the project directory, in a terminal the user watches. Returns what it wrote, stdout and stderr "
    "together in the order written, byte for byte (tabs, trailing spaces, carriage returns and escape codes are kept), and the "
    "exit code if it failed. Its stdout is not a terminal and its input is closed, so most programs print plain text, without "
    "colour or progress bars. An interactive command runs on the terminal instead, and you get its screen as the user saw it: "
    "escape codes and carriage returns are applied and gone. Output too large to return is saved to a file and you are told where.",
    PARAMETERS,
    bash,
)
