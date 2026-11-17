"""std/void/tag.py: the void tag, put on a message and taken off without touching its text."""

from llvim.core import Message
from llvim.std.conversation import decode, encode
from llvim.std.cues import is_cue
from llvim.std.void.tag import VOID, is_void, marked, unmarked


def test_marking_adds_the_tag_after_the_others_and_keeps_the_fields_and_the_text():
    message = encode(["assistant"], "héllo\nworld", model="m")
    voided = decode(Message(0, marked(message, True)))
    assert (voided.tags, voided.content, voided.extra) == (
        ["assistant", VOID],
        "héllo\nworld",
        {"model": "m"},
    ) and is_void(voided)


def test_unmarking_gives_back_the_message_as_it_was():
    message = encode(["user"], "hi")
    assert marked(marked(message, True), False) == message


def test_marking_that_changes_nothing_or_a_message_with_no_tags_is_none():
    message = encode(["user"], "hi")
    assert marked(message, False) is None and marked(marked(message, True), True) is None
    for unformatted in (b"just bytes", b"not json\nbody", b'{"no": "tags"}\nbody'):
        assert marked(unformatted, True) is None, unformatted


def test_a_voided_cue_is_no_longer_a_cue_and_unmarked_it_reads_as_one_again(entry):
    cue = entry(["cue", "generate", VOID])
    assert not is_cue(cue) and is_cue(unmarked(cue)) and unmarked(cue).id == cue.id
