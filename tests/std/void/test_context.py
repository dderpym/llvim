"""std/void/context.py: the context renderer that leaves voided messages out."""

from llvim.std.void import CONTEXT


def test_voided_messages_are_left_out_whatever_they_are_and_the_rest_keep_their_order(entry):
    log = [
        entry(["user"], "a"), entry(["assistant", "void"], "b"), entry(["tool_call", "bash", "void"], "{}", call_id="x"),
        entry(["cue", "generate", "void"]), entry(["assistant"], "d"),
    ]  # fmt: skip
    assert [e.content for e in CONTEXT(log)] == ["a", "d"]
