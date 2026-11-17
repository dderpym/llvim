"""std/tools/bash/tool.py: TOOL, the bash tool: run a shell command in the project folder, in a terminal the user watches, and
return what it printed, shaped for the model; and TERMINAL, a terminal kept open that the model and the user take turns at."""

import os
import signal
import statistics
import tempfile
import time
import uuid

from llvim.std.tmux import TmuxError
from llvim.std.tools.bash import shared, terminal
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

TERMINAL_PARAMETERS = {
    "type": "object",
    "properties": {
        "command": {
            "type": "string",
            "description": "Start this bash command on a new terminal, whose id is this call's id. Leave out id.",
        },
        "id": {"type": "string", "description": "The terminal to take a turn at, from the call that started it."},
        "keys": {
            "type": "string",
            "description": "Text to type. A newline is Enter. Control keys as JSON escapes: \\u0003 is ctrl-c, \\u0004 ctrl-d, "
            "\\u001b escape.",
        },
        "give_to_user": {
            "type": "string",
            "description": 'Hand the keyboard to the user, saying what they need to do ("type your sudo password"). Use it for '
            "what only they should type: passwords, passphrases, choices that are theirs. Waits until they hand it back.",
        },
        "close": {"type": "boolean", "description": "Stop the program (ctrl-c, then kill) and close the terminal."},
        "timeout": {
            "type": "number",
            "description": "Seconds to wait for the screen to be still. Leave it out for the default. Nothing is stopped when it runs out.",
        },
    },
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


def told(seen: shared.Seen, id: str, waited: float, handing: bool = False) -> str:
    """What the model is told of a look at a kept terminal: what is new, then how the look ended and whether it still runs."""
    output = shown(seen.output) if seen.output else "(nothing new)"
    if not seen.running:
        how = "stopped" if seen.status is None else ended(seen.status)
        return f"{output}\n[{how}; the terminal is closed]"
    if seen.cancelled:
        raise ToolError(f"{output}\n[interrupted; still running in terminal {id}]")
    if seen.handed_back:
        how = "the user handed it back. "
    elif handing:
        how = f"the user did not hand it back within {waited:g}s; it is yours again. "
    elif seen.still_changing:
        how = f"still printing after {waited:g}s. "
    else:
        how = ""
    return f"{output}\n[{how}running in terminal {id}: use the terminal tool to type, look again, give it to the user, or close it]"


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
    "Run a command in the project directory, in a terminal the user watches. Returns stdout and stderr together, verbatim "
    "(escape codes kept), plus exit code if it failed. stdin is closed and stdout is not a tty — prompting commands fail; use "
    "terminal instead. Large output goes to a file and you're told where. timeout stops it. interactive runs it on the real "
    "terminal for things only the user should type.",
    PARAMETERS,
    bash,
)


async def take_turn(arguments: dict, ctx: Context) -> str:
    asked = [a for a in ("command", "keys", "give_to_user", "close") if arguments.get(a) not in (None, False)]
    if len(asked) > 1:
        raise ToolError(f"one of command, keys, give_to_user and close per call, not {' and '.join(asked)}")
    if "command" in asked:
        return await start(arguments, ctx)
    if not arguments.get("id"):
        raise ToolError("give a command to start a terminal, or the id of one to take a turn at")
    id = arguments["id"]
    try:
        if arguments.get("close"):
            return told(await shared.close(id), id, 0)
        if arguments.get("give_to_user"):
            waited = setting("user_timeout")
            return told(await shared.hand_to_user(id, waited), id, waited, handing=True)
        waited = float(arguments.get("timeout") or setting("timeout"))
        return told(await shared.type_keys(id, arguments.get("keys") or "", waited, setting("settle")), id, waited)
    except shared.Closed as e:
        raise ToolError(str(e)) from None


async def start(arguments: dict, ctx: Context) -> str:
    id = (ctx.call and call_id(ctx.call)) or f"term_{uuid.uuid4().hex[:12]}"
    waited = float(arguments.get("timeout") or setting("timeout"))
    try:
        seen = await shared.start(arguments["command"], ctx.cwd, id, waited, setting("settle"))
    except TmuxError as e:
        raise ToolError(f"terminal needs a tmux terminal, and could not get one: {e}") from None
    return told(seen, id, waited)


TERMINAL = Tool(
    "terminal",
    "A terminal that stays open between calls, for programs you type into: REPLs, ssh, installers that ask questions, "
    "password prompts. For a command that just runs and exits, use bash.\n"
    '1. Start: {"command": "python3"}. Returns the screen once it is still, and the terminal\'s id.\n'
    '2. Type: {"id": ..., "keys": "print(1)\\n"}. A newline is Enter, \\u0003 is ctrl-c. Returns what is new, from the line '
    "the cursor was on; a full-screen program (vim, top) gives its whole screen. With no keys it waits and looks again: use "
    "that while a program is still working.\n"
    '3. Hand over: {"id": ..., "give_to_user": "type your sudo password"} for what is the user\'s to type: passwords, '
    "passphrases, choices only they should make. Never ask them for a password in chat. You see nothing while they have it; "
    "the call returns when they hand it back (or after an hour), with what happened.\n"
    '4. Close: {"id": ..., "close": true} when done: ctrl-c, then kill. A program that exits closes its terminal itself.\n'
    "State persists between calls: variables, cwd, running programs. One of command, keys, give_to_user or close per call. "
    "timeout limits the wait; it never stops the program.",
    TERMINAL_PARAMETERS,
    take_turn,
)
