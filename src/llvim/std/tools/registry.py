"""std/tools/registry.py: Tool, a function a model may call, described once for any provider; Registry, the tools one program
was given; Context, Result and ToolError."""

from __future__ import annotations

import asyncio
import dataclasses
import inspect
import json
import threading
from collections.abc import Awaitable, Callable, Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from llvim.core import Log, Writer
from llvim.std.conversation import Entry


class ToolError(RuntimeError):
    """Raised by a tool to say its call failed. The message goes back to the model as the result."""


@dataclass(frozen=True)
class Context:
    """What a tool gets besides its arguments. `writer` is the runner's, held for the whole call, and only an async tool gets it:
    a Writer is not safe to use from another thread. `cancelled` is set when a sync tool should stop."""

    cwd: Path = field(default_factory=Path.cwd)
    call: Entry | None = None
    log: Log | None = None
    writer: Writer | None = None
    cancelled: threading.Event = field(default_factory=threading.Event)


@dataclass(frozen=True)
class Result:
    text: str
    error: bool = False


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict  # JSON Schema of the arguments: {"type": "object", "properties": {...}, "required": [...]}
    run: Callable[[dict, Context], str | Awaitable[str]]

    @property
    def is_async(self) -> bool:
        return inspect.iscoroutinefunction(self.run)


def tool(name: str, description: str, parameters: dict):
    """Decorator: the function, sync or async, as a `Tool`."""
    return lambda fn: Tool(name, description, parameters, fn)


TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list, "object": dict}


def check(schema: dict, arguments: Any) -> str | None:
    """What is wrong with `arguments` for this schema, in words the model can act on, or None. Only what models get wrong: not an
    object, a missing required argument, a wrong simple type."""
    if not isinstance(arguments, dict):
        return f"the arguments must be a JSON object, got {type(arguments).__name__}"
    for name in schema.get("required", []):
        if name not in arguments:
            return f"{name!r} is required"
    for name, value in arguments.items():
        expected = schema.get("properties", {}).get(name, {}).get("type")
        python = TYPES.get(expected)
        if python and (not isinstance(value, python) or (isinstance(value, bool) and expected != "boolean")):
            return f"{name!r} must be {expected}, got {json.dumps(value)[:40]}"
    return None


class Registry:
    def __init__(self, tools: Iterable[Tool] = ()) -> None:
        self._tools: dict[str, Tool] = {}
        for t in tools:
            self.register(t)

    def register(self, tool: Tool, replace: bool = False) -> Tool:
        """Registering a name twice is an error unless `replace` says you mean it."""
        if tool.name in self._tools and not replace:
            raise ValueError(f"a tool named {tool.name!r} is already registered")
        self._tools[tool.name] = tool
        return tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def __iter__(self) -> Iterator[Tool]:
        return iter(list(self._tools.values()))

    def __contains__(self, name: object) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)

    async def run(self, name: str, arguments: str | dict, ctx: Context | None = None) -> Result:
        """Call a tool the way a model asked. Never raises for a bad call: what is wrong comes back as an error Result.
        Cancelled, an async tool is cancelled; a sync one has `ctx.cancelled` set and is waited for."""
        tool = self.get(name)
        if tool is None:
            return Result(f"unknown tool {name!r}; the tools are: {', '.join(self._tools) or 'none'}", error=True)
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments.strip() or "{}")  # a tool with no arguments may send nothing
            except ValueError as e:
                return Result(f"{name}: the arguments are not valid JSON ({e})", error=True)
        if problem := check(tool.parameters, arguments):
            return Result(f"{name}: {problem}", error=True)
        ctx = ctx or Context()
        try:
            if tool.is_async:
                return Result(str(await tool.run(arguments, ctx)))
            return Result(str(await _in_thread(tool, arguments, dataclasses.replace(ctx, writer=None))))
        except ToolError as e:
            return Result(str(e), error=True)
        except Exception as e:
            return Result(f"{name} failed: {type(e).__name__}: {e}", error=True)


async def _in_thread(tool: Tool, arguments: dict, ctx: Context) -> Any:
    # A thread cannot be stopped from outside, so a cancel becomes `ctx.cancelled` and the tool's own answer is still awaited:
    # what it had done by then is the result.
    running = asyncio.ensure_future(asyncio.to_thread(tool.run, arguments, ctx))
    try:
        return await asyncio.shield(running)
    except asyncio.CancelledError:
        ctx.cancelled.set()
        return await running
