"""std/tools/calls.py: how tool calls look in a log, and which are still waiting or were cut off."""

from llvim.core import Message
from llvim.std.conversation import decode
from llvim.std.tools.calls import CALL, RESULT, START, answer, by_user, call, call_id, cut_off, kind, name, pending


def log(entry, *items):
    """Entries from short items: ("user",), ("call", id), ("mine", id) (a call the user made), ("start", id), ("result", id)."""
    out = []
    for item, *rest in items:
        if item == "user":
            out.append(entry(["user"], "x"))
        elif item in ("call", "mine"):
            out.append(entry([CALL, "bash"], "{}", call_id=rest[0], **({"user": True} if item == "mine" else {})))
        else:
            out.append(entry([{"start": START, "result": RESULT}[item], "bash"], "", call_id=rest[0]))
    return out


def ids(entries):
    return [call_id(e) for e in entries]


def test_a_call_names_its_tool_and_id_and_a_start_or_result_carries_them_and_whether_the_user_made_it():
    mine = decode(Message(0, call("bash", '{"command": "ls"}', "c1", user=True)))
    assert (kind(mine), name(mine), call_id(mine), by_user(mine), mine.content) == (
        CALL,
        "bash",
        "c1",
        True,
        '{"command": "ls"}',
    )
    result = decode(Message(1, answer(RESULT, mine, "a.txt", error=False)))
    assert (result.tags, result.content, result.extra) == (
        [RESULT, "bash"],
        "a.txt",
        {"call_id": "c1", "user": True, "error": False},
    )


def test_a_message_that_is_not_about_a_call_names_no_tool(entry):
    for tags in (["user"], ["cue", "tools"], [CALL], [CALL, 3]):
        assert name(entry(tags)) == "", tags


def test_a_call_waits_until_it_has_a_result(entry):
    assert ids(pending(log(entry, ("user",), ("call", "a"), ("call", "b"), ("result", "a")))) == ["b"]


def test_a_call_the_user_has_spoken_over_is_not_waited_for(entry):
    assert ids(pending(log(entry, ("call", "old"), ("user",), ("call", "a"), ("call", "b")))) == ["a", "b"]


def test_a_call_the_user_made_is_still_waited_for_after_they_speak(entry):
    assert ids(pending(log(entry, ("mine", "m"), ("user",)))) == ["m"]


def test_a_result_that_comes_after_the_user_spoke_still_answers_its_call(entry):
    assert pending(log(entry, ("call", "a"), ("user",), ("result", "a"))) == []


def test_a_call_with_a_start_and_no_result_was_cut_off_spoken_over_or_not(entry):
    entries = log(
        entry, ("call", "a"), ("start", "a"), ("call", "b"), ("start", "b"), ("result", "b"), ("user",), ("call", "c")
    )
    assert ids(cut_off(entries)) == ["a"]
