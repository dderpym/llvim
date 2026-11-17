"""std/context.py: context renderers, applied in order between a log and a program that reads it as a conversation."""

from llvim.std.context import render


def test_with_no_renderers_the_entries_are_the_conversation(entry):
    log = [entry(["user"], "hi")]
    assert render(log, []) == log


def test_each_renderer_gets_what_the_one_before_it_left(entry):
    log = [entry(["user"], "a"), entry(["assistant"], "b"), entry(["user"], "c")]
    seen = []

    def no_assistant(entries):
        return [e for e in entries if e.tags != ["assistant"]]

    def note(entries):
        seen.append([e.content for e in entries])
        return entries[-1:]

    assert [e.content for e in render(log, [no_assistant, note])] == ["c"] and seen == [["a", "c"]]
