"""std/tools/registry.py: tools described once, and a call run the way a model asked, sync or async."""

import asyncio
import threading

import pytest

from llvim.std.tools import Context, Registry, Result, Tool, ToolError, check, tool

ADD = {"type": "object", "properties": {"a": {"type": "number"}, "b": {"type": "number"}}, "required": ["a", "b"]}
ANY = {"type": "object"}


@pytest.fixture
def registry():
    return Registry([Tool("add", "Add two numbers.", ADD, lambda args, ctx: args["a"] + args["b"])])


def test_a_registry_lists_its_tools_by_name_and_in_order(registry):
    registry.register(Tool("two", "Second.", ANY, lambda a, c: "2"))
    assert [t.name for t in registry] == ["add", "two"] and "add" in registry and len(registry) == 2
    assert registry.get("add").parameters["required"] == ["a", "b"] and registry.get("nope") is None


def test_a_name_may_be_registered_once_unless_replacing(registry):
    with pytest.raises(ValueError, match="already registered"):
        registry.register(registry.get("add"))
    registry.register(Tool("add", "Plus.", ANY, lambda a, c: "x"), replace=True)
    assert registry.get("add").description == "Plus."


async def test_the_decorator_makes_a_function_sync_or_async_a_tool_and_registers_nothing():
    @tool("shout", "Shout.", ANY)
    def shout(args, ctx):
        return "HEY"

    @tool("whisper", "Whisper.", ANY)
    async def whisper(args, ctx):
        return "hey"

    assert isinstance(shout, Tool) and not shout.is_async and whisper.is_async
    assert (await Registry([shout]).run("shout", "{}")).text == "HEY"
    assert (await Registry([whisper]).run("whisper", "{}")).text == "hey"


async def test_a_call_may_come_as_json_text_or_already_parsed_and_no_arguments_is_an_empty_object(registry):
    assert (await registry.run("add", '{"a": 1, "b": 2.5}')).text == "3.5"
    assert (await registry.run("add", {"a": 1, "b": 2})).text == "3"
    registry.register(Tool("none", "x", ANY, lambda a, c: repr(a)))
    assert (await registry.run("none", "  ")).text == "{}"


async def test_a_bad_call_comes_back_as_an_error_result_that_says_what_to_fix(registry):
    for name, arguments, says in [
        ("nope", "{}", "unknown tool 'nope'; the tools are: add"),
        ("add", "{not json", "not valid JSON"),
        ("add", "[1, 2]", "must be a JSON object"),
        ("add", '{"a": 1}', "'b' is required"),
        ("add", '{"a": true, "b": 2}', "'a' must be number"),  # a boolean is not a number
    ]:
        result = await registry.run(name, arguments)
        assert result.error and says in result.text, (name, arguments)


async def test_a_tool_that_fails_is_an_error_result_not_an_exception(registry):
    def refuse(a, c):
        raise ToolError("not allowed")

    registry.register(Tool("boom", "x", ANY, lambda a, c: 1 / 0))
    registry.register(Tool("polite", "x", ANY, refuse))
    assert await registry.run("boom", "{}") == Result("boom failed: ZeroDivisionError: division by zero", error=True)
    assert await registry.run("polite", "{}") == Result("not allowed", error=True)


def test_check_says_only_what_models_get_wrong():
    schema = {"type": "object", "properties": {"n": {"type": "integer"}, "s": {"type": "string"}}, "required": ["s"]}
    for arguments, problem in [
        ({"s": "x", "n": 3}, None),
        ({"s": "x", "extra": [1]}, None),  # an argument it does not know is let through
        ({"n": 3}, "'s' is required"),
        ({"s": "x", "n": 1.5}, "'n' must be integer, got 1.5"),
        ({"s": "x", "n": False}, "'n' must be integer, got false"),
        ("x", "the arguments must be a JSON object, got str"),
    ]:
        assert check(schema, arguments) == problem, arguments


async def test_an_async_tool_gets_the_writer_and_a_sync_one_does_not():
    seen = {}

    async def in_loop(a, ctx):
        seen["async"] = ctx.writer
        return ""

    def in_thread(a, ctx):
        seen["sync"] = ctx.writer
        return ""

    registry = Registry([Tool("a", "x", ANY, in_loop), Tool("s", "x", ANY, in_thread)])
    for name in ("a", "s"):
        await registry.run(name, "{}", Context(writer="the writer"))
    assert seen == {"async": "the writer", "sync": None}  # a Writer is not safe to use from another thread


async def test_a_cancelled_async_tool_is_cancelled():
    started, cleaned_up = asyncio.Event(), []

    async def slow(a, ctx):
        started.set()
        try:
            await asyncio.sleep(30)
        finally:
            cleaned_up.append(True)

    running = asyncio.ensure_future(Registry([Tool("slow", "x", ANY, slow)]).run("slow", "{}"))
    await started.wait()
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    assert cleaned_up == [True]


async def test_a_cancelled_sync_tool_is_told_to_stop_and_its_answer_is_still_the_result():
    started = threading.Event()

    def slow(a, ctx):
        started.set()
        ctx.cancelled.wait(5)
        return "stopped early" if ctx.cancelled.is_set() else "ran out"

    running = asyncio.ensure_future(Registry([Tool("slow", "x", ANY, slow)]).run("slow", "{}"))
    await asyncio.to_thread(started.wait, 5)
    running.cancel()
    assert await running == Result("stopped early")
