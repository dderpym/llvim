"""std/conversation.py: Entry, the message format the standard programs agree on."""

from llvim.core import Message, Snapshot
from llvim.std.conversation import Entry, decode, encode, entries


def test_a_message_is_its_tags_and_fields_then_its_text_and_reads_back_as_written():
    content = encode(["assistant", {"n": 1}], "hé\nllo", model="m")
    assert content.split(b"\n")[0] == '{"tags": ["assistant", {"n": 1}], "model": "m"}'.encode()
    assert decode(Message(7, content)) == Entry(7, ["assistant", {"n": 1}], "hé\nllo", {"model": "m"})


def test_text_added_to_the_end_of_a_message_is_more_of_its_text():
    assert decode(Message(0, encode(["assistant"], "Hel") + "lo".encode())).content == "Hello"


def test_a_message_in_no_known_format_is_an_untagged_entry_of_its_text():
    for content in (b"plain", b"[1]\nx", b"{bad\nx", b'{"tags": 1}\nx', b"\xff\nx"):
        entry = decode(Message(0, content))
        assert entry.tags == [] and entry.content == content.decode(errors="replace"), content


def test_of_a_snapshot_the_uncommitted_entries_are_marked_and_the_last_of_them_is_streaming():
    one, two, three = (Message(i, encode(["n"], str(i))) for i in range(3))
    read = entries(Snapshot("c", (one, two, three), uncommitted=(two, three)))
    assert [(e.uncommitted, e.streaming) for e in read] == [(False, False), (True, False), (True, True)]
    finished = entries(Snapshot("c", (one, two, three), uncommitted=(two,)))
    assert [e.streaming for e in finished] == [False, False, False]
