"""core/live.py: the journal of uncommitted writes, and View, the head with a journal applied."""

from llvim.core.live import Message, Snapshot, View, record, records

HEAD = "a" * 40
OLD = "b" * 40
CONTENTS = {HEAD: {0: b"a", 1: b"b"}, OLD: {0: b"old"}}


def view(journal: bytes) -> View:
    view = View(HEAD, ("key", 1), CONTENTS[HEAD])
    view.take(journal, CONTENTS.__getitem__)
    return view


def test_a_record_still_being_written_is_left_out():
    whole = record(b"S", 1, b"hello")
    assert list(records(whole + whole[:-2])) == [(b"S", 1, b"hello")]
    assert list(records(whole + whole[:3])) == [(b"S", 1, b"hello")]


def test_a_journal_read_in_pieces_gives_what_it_gives_read_whole():
    journal = b"".join([
        record(b"B", 0, HEAD.encode()),
        record(b"E", 0, b"+"),
        record(b"S", 2, b"c"),
        record(b"E", 2, b"d"),
        record(b"D", 1, b""),
        record(b"S", 3, b"e"),
        record(b"R", 0, OLD.encode()),
        record(b"S", 1, b"back"),
    ])
    whole = view(journal).snapshot()
    for cut in range(len(journal) + 1):
        pieces = view(journal[:cut])
        pieces.snapshot()
        pieces.take(journal[pieces.offset :], CONTENTS.__getitem__)
        assert pieces.snapshot() == whole, f"cut at {cut}"


def test_uncommitted_and_removed_are_measured_against_the_head():
    journal = record(b"B", 0, HEAD.encode()) + b"".join([
        record(b"E", 0, b"+"),
        record(b"D", 1, b""),
        record(b"S", 2, b"gone again"),
        record(b"D", 2, b""),
    ])
    assert view(journal).snapshot() == Snapshot(
        HEAD, (Message(0, b"a+"),), uncommitted=(Message(0, b"a+"),), removed=(Message(1, b"b"),)
    )


def test_a_journal_written_on_another_head_is_not_applied():
    journal = record(b"B", 0, OLD.encode()) + record(b"S", 5, b"stale")
    assert view(journal).snapshot() == Snapshot(HEAD, (Message(0, b"a"), Message(1, b"b")))


def test_a_restore_record_makes_the_messages_those_of_its_commit():
    journal = record(b"B", 0, HEAD.encode()) + record(b"R", 0, OLD.encode())
    assert view(journal).snapshot().messages == (Message(0, b"old"),)


def test_a_read_that_finds_nothing_new_gives_the_same_snapshot():
    live = view(record(b"B", 0, HEAD.encode()) + record(b"S", 2, b"c"))
    first = live.snapshot()
    live.take(b"", CONTENTS.__getitem__)
    assert live.snapshot() is first


def test_file_records_do_not_change_the_messages():
    journal = record(b"B", 0, HEAD.encode()) + record(b"F", 0, b"a\0" + b"1" * 40) + record(b"T", 0, b"f\0")
    snapshot = view(journal).snapshot()
    assert snapshot.messages == (Message(0, b"a"), Message(1, b"b"))
    assert snapshot.uncommitted == snapshot.removed == ()
