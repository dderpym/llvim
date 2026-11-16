"""std/panels/logviewer/document.py: the log as slots, boxes made when shown, rows worked out when needed, and anchors to
scroll by."""

from llvim.core import Request
from llvim.std.conversation import encode
from llvim.std.panels.logviewer import boxes
from llvim.std.panels.logviewer.box import Box, alone, box
from llvim.std.panels.logviewer.document import Document


def notes(fake_log, n, prefix="line"):
    for i in range(n):
        fake_log.say(["note"], f"{prefix} {i}")


def synced(doc, fake_log):
    return doc.sync(fake_log.read())


# --- slots, and boxes made when they are shown ---


def test_each_message_is_a_slot_and_nothing_is_made_until_it_is_asked_for(fake_log, stub_host):
    doc = Document(stub_host)
    notes(fake_log, 500)
    assert synced(doc, fake_log) and len(doc.slots) == 500 and not any(s.box for s in doc.slots)
    doc.window(doc.slots[0], 0, 24, 40)
    assert 1 <= sum(1 for s in doc.slots if s.box) <= 12  # what a screenful needs, of five hundred


def test_reading_the_same_log_again_changes_nothing(fake_log, stub_host):
    doc = Document(stub_host)
    notes(fake_log, 3)
    assert synced(doc, fake_log) and not synced(doc, fake_log)


def test_a_box_without_on_messages_is_made_again_when_its_messages_change_and_the_old_one_is_closed(fake_log, stub_host):
    made = []

    @box(lambda m: m.extra.get("g"))
    class Plain(Box):
        def __init__(self, host, messages):
            super().__init__(host, messages)
            made.append(self)
            self.lines = [str(len(messages))]

    doc = Document(stub_host, [Plain])
    fake_log.say(["n"], g="one")
    synced(doc, fake_log)
    first = doc.box_of(doc.slots[0])
    fake_log.say(["n"], g="one")
    synced(doc, fake_log)
    second = doc.box_of(doc.slots[0])
    assert len(made) == 2 and second is not first and second.lines == ["2"] and first.closed.is_set()


def test_a_box_with_on_messages_is_kept_and_given_the_new_messages(fake_log, stub_host):
    kept = []

    @box(lambda m: m.extra.get("g"))
    class Keeps(Box):
        def __init__(self, host, messages):
            super().__init__(host, messages)
            kept.append(self)
            host.on_messages(self, lambda messages: setattr(self, "lines", [str(len(messages))]))

    doc = Document(stub_host, [Keeps])
    fake_log.say(["n"], g="x")
    synced(doc, fake_log)
    mine = doc.box_of(doc.slots[0])
    fake_log.say(["n"], g="x")
    synced(doc, fake_log)
    assert doc.box_of(doc.slots[0]) is mine and len(kept) == 1 and mine.lines == ["2"] and len(mine.messages) == 2


async def test_a_streaming_message_keeps_its_slot_as_it_grows_and_when_it_is_committed(fake_log, stub_host):
    doc = Document(stub_host)
    notes(fake_log, 2)
    async with await fake_log.claim(Request(0)) as writer:
        reply = writer.append(encode(["assistant"], "hel"))
        synced(doc, fake_log)
        slot = doc.slots[-1]
        assert slot.messages[0].streaming
        writer.extend(reply, b"lo")
        synced(doc, fake_log)
        assert doc.slots[-1] is slot and slot.messages[0].content == "hello"
        await writer.commit()
        synced(doc, fake_log)
        assert doc.slots[-1] is slot and not slot.messages[0].streaming and not slot.messages[0].uncommitted


def test_messages_that_did_not_change_are_not_claimed_again(fake_log, stub_host):
    asked = []
    doc = Document(stub_host, [box(lambda m: asked.append(m.content) or None)(Box)])
    notes(fake_log, 5, "c")
    synced(doc, fake_log)
    assert asked == [f"c {i}" for i in range(5)]
    asked.clear()
    fake_log.say(["note"], "c 5")
    synced(doc, fake_log)
    fake_log.write(["note"], "t0")
    synced(doc, fake_log)
    assert asked == ["c 5", "t0"]


async def test_a_message_removed_from_the_log_takes_its_slot_and_box_with_it(fake_log, stub_host):
    doc = Document(stub_host)
    notes(fake_log, 2)
    async with await fake_log.claim(Request(0)) as writer:
        going = writer.append(encode(["note"], "going"))
        synced(doc, fake_log)
        box = doc.box_of(doc.slots[-1])
        writer.remove(going)
        synced(doc, fake_log)
    assert len(doc.slots) == 2 and box.closed.is_set()


def test_slots_keep_the_order_of_their_first_messages_when_a_late_message_joins_an_early_slot(fake_log, stub_host):
    doc = Document(stub_host, [box(lambda m: m.extra.get("g"))(type("Group", (Box,), {}))])
    fake_log.say(["n"], "a", g="one")
    fake_log.say(["n"], "b", g="two")
    synced(doc, fake_log)
    fake_log.write(["n"], "c", g="one")
    synced(doc, fake_log)
    assert [[m.content for m in s.messages] for s in doc.slots] == [["a", "c"], ["b"]]


# --- rows ---


def test_a_box_that_draws_itself_is_worked_out_again_only_when_something_says_so(fake_log, stub_host):
    drawn = []

    @box(lambda m: alone(m) if m.tags == ["mine"] else None)
    class Draws(Box):
        def __init__(self, host, messages):
            super().__init__(host, messages)
            host.layout(self, lambda cols: drawn.append(cols) or ["drawn"])

    doc = Document(stub_host, [Draws])
    fake_log.say(["mine"])
    synced(doc, fake_log)
    mine = doc.slots[0]
    for _ in range(3):
        doc.rows_for(mine, 40)
    assert drawn == [40]
    doc.box_of(mine).changed()
    doc.rows_for(mine, 40)
    doc.stale()
    doc.rows_for(mine, 40)
    doc.rows_for(mine, 60)
    assert drawn == [40, 40, 40, 60]


def test_a_box_that_raises_in_its_layout_shows_the_fallback_rows(fake_log, stub_host):
    @box(lambda m: alone(m) if m.tags == ["stuck"] else None)
    class Stuck(Box):
        def __init__(self, host, messages):
            super().__init__(host, messages)
            host.layout(self, self.draw)

        def draw(self, cols):
            raise RuntimeError("cannot draw")

    doc = Document(stub_host, [Stuck])
    fake_log.say(["stuck"], "readable anyway")
    synced(doc, fake_log)
    assert any("readable anyway" in r for r in doc.window(doc.slots[0], 0, 10, 40).rows)
    assert doc.replace_failed() and type(doc.slots[0].box) is boxes.Fallback


# --- places to scroll by ---


def test_scrolling_walks_from_the_anchor_up_and_back_down_to_the_end(fake_log, stub_host):
    doc = Document(stub_host)
    notes(fake_log, 60)
    synced(doc, fake_log)
    anchor, offset = doc.end_position(20, 40)
    end_rows = doc.window(anchor, offset, 20, 40).rows
    up, off, at_end = doc.move(anchor, offset, -30, 20, 40)
    assert not at_end and doc.window(up, off, 20, 40).rows != end_rows
    down, off2, at_end = doc.move(up, off, 30, 20, 40)
    assert at_end and doc.window(down, off2, 20, 40).rows == end_rows


def test_text_that_arrives_while_you_read_higher_up_does_not_move_what_you_see(fake_log, stub_host):
    doc = Document(stub_host)
    notes(fake_log, 40)
    synced(doc, fake_log)
    anchor, offset, _ = doc.move(*doc.end_position(20, 40), -200, 20, 40)
    before = doc.window(anchor, offset, 20, 40).rows
    notes(fake_log, 10, "new")
    assert synced(doc, fake_log) and doc.window(anchor, offset, 20, 40).rows == before
