"""std/tools/calls.py: how tool calls look in a log, for the providers that write them, the runner that answers them, and the
viewers that show them."""

from llvim.std.conversation import Entry, Field, Tag, encode

CALL, START, RESULT = Tag.TOOL_CALL, Tag.TOOL_START, Tag.TOOL_RESULT


def call_id(entry: Entry) -> str | None:
    return entry.extra.get(Field.CALL_ID)


def name(entry: Entry) -> str:
    """The tool a call, start or result is for."""
    tags = entry.tags
    return tags[1] if len(tags) > 1 and tags[0] in (CALL, START, RESULT) and isinstance(tags[1], str) else ""


def kind(entry: Entry) -> object:
    """CALL, START, RESULT, or something else: the first tag."""
    return entry.tags[0] if entry.tags else None


def by_user(entry: Entry) -> bool:
    return bool(entry.extra.get(Field.USER))


def call(tool: str, arguments: str, id: str, **extra) -> bytes:
    return encode([CALL, tool], arguments, **{Field.CALL_ID: id}, **extra)


def answer(tag: Tag, of: Entry, content: str = "", **extra) -> bytes:
    """The start or the result of a call: its tool and id, and whether the user made it."""
    user = {Field.USER: True} if by_user(of) else {}
    return encode([tag, name(of)], content, **{Field.CALL_ID: call_id(of)}, **user, **extra)


def pending(entries: list[Entry]) -> list[Entry]:
    """The calls with no result that the user has not spoken over, oldest first. A call the user made stays theirs to wait for."""
    answered = {call_id(e) for e in entries if kind(e) == RESULT}
    waiting: list[Entry] = []
    for e in entries:
        if Tag.USER in e.tags:
            waiting = [c for c in waiting if by_user(c)]
        elif kind(e) == CALL and call_id(e) not in answered:
            waiting.append(e)
    return waiting


def cut_off(entries: list[Entry]) -> list[Entry]:
    """The calls that have a start and no result, spoken over or not, oldest first. Found by a runner that holds the log, they are
    calls a runner took and died running."""
    answered = {call_id(e) for e in entries if kind(e) == RESULT}
    started = {call_id(e) for e in entries if kind(e) == START} - answered
    return [e for e in entries if kind(e) == CALL and call_id(e) in started]
