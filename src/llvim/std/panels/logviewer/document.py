"""std/panels/logviewer/document.py: Document, the log as slots of messages, each shown by a box, and scrolled over as one."""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import NamedTuple

from llvim.core import Message, Snapshot
from llvim.std.conversation import Entry, decode
from llvim.std.panels.logviewer import boxes
from llvim.std.panels.logviewer.ansi import wrap
from llvim.std.panels.logviewer.box import Box, Host, Renderer, chain, claimed, make


@dataclass(eq=False)
class Slot:
    """The messages one renderer claimed under one key. Its box is made when it is first shown."""

    key: tuple
    renderer: Renderer
    messages: list[Entry] = field(default_factory=list)
    box: Box | None = None
    stale: bool = True  # its messages are not what its box has


class Place(NamedTuple):
    slot: Slot
    box: Box
    top: int  # the screen row of its first row: negative if it starts above the screen
    height: int


class Window(NamedTuple):
    rows: list[str]  # exactly as many as asked for
    places: list[Place]
    at_end: bool  # the last row of the log is in view


class Document:
    def __init__(self, host: Host, renderers: Iterable[Renderer] = ()):
        self.host = host
        self.chain = chain(renderers)
        self.slots: list[Slot] = []
        self._messages: tuple[Message, ...] = ()
        self._first_uncommitted = 0
        self._keys: list[tuple | None] = []  # the group of each message, by position
        self._groups: dict[tuple, Slot] = {}  # in the order of their first messages
        self._made: set[Slot] = set()  # the slots that have a box
        self._epoch = 0  # raised when something changed that no box said (see `stale`)

    def sync(self, snapshot: Snapshot) -> bool:
        """Take the log as `snapshot` has it. True if what is shown may be different now."""
        messages = snapshot.messages
        uncommitted = {m.id for m in snapshot.uncommitted}
        first_uncommitted = bisect_left(messages, min(uncommitted, default=float("inf")), key=lambda m: m.id)
        keep = self._unchanged(messages, first_uncommitted)
        if keep == len(messages) == len(self._messages):
            return False
        dropped = self._drop_from(keep)
        last = messages[-1].id if messages else None
        for message in messages[keep:]:
            fresh = message.id in uncommitted
            entry = decode(message, fresh, fresh and message.id == last)
            i, key = claimed(self.chain, entry)
            group = None if i is None else (i, key)
            self._keys.append(group)
            if group is None:
                continue
            slot = self._groups.get(group) or dropped.pop(group, None) or Slot(group, self.chain[i])
            self._groups[group] = slot
            slot.messages.append(entry)
            slot.stale = True
        for slot in dropped.values():
            self._close(slot)
        self._messages, self._first_uncommitted = messages, first_uncommitted
        self.slots = list(self._groups.values())
        return True

    def _unchanged(self, messages: tuple[Message, ...], first_uncommitted: int) -> int:
        """How many messages from the start are the same committed messages as last time."""
        old = self._messages
        limit = min(len(messages), len(old), first_uncommitted, self._first_uncommitted)
        kept = 0
        while kept < limit and (old[kept] is messages[kept] or old[kept] == messages[kept]):
            kept += 1
        return kept

    def _drop_from(self, keep: int) -> dict[tuple, Slot]:
        """Take the messages from position `keep` on out of their slots. Returns the slots left empty, so a message that comes
        back to its group gets its old slot, and its box, again."""
        dropped = {}
        for position in range(len(self._keys) - 1, keep - 1, -1):
            if (group := self._keys[position]) is None:
                continue
            slot = self._groups[group]
            slot.messages.pop()
            slot.stale = True
            if not slot.messages:
                dropped[group] = self._groups.pop(group)
        del self._keys[keep:]
        return dropped

    def _close(self, slot: Slot) -> None:
        if slot.box is not None:
            slot.box.close()
            self._made.discard(slot)
            slot.box = None

    # --- boxes ---

    def box_of(self, slot: Slot) -> Box:
        """The slot's box, made now if it has none, and given the slot's messages if they changed."""
        box, messages = slot.box, list(slot.messages)
        if box is not None and box.error is None and slot.stale and box.messages != messages:
            if box.hooks.on_messages:
                try:
                    box.hooks.on_messages(messages)
                    box.messages = messages
                except Exception as e:
                    box.error = e
            else:
                box.close()
                box = None
        slot.stale = False
        if box is None or box.error is not None:
            if box is not None:
                box.close()
            self._made.add(slot)
            box = slot.box = make(slot.renderer, self.host, messages)
        return box

    def replace_failed(self) -> bool:
        """Swap the fallback in for any box that raised. True if one was."""
        failed = [s for s in self._made if s.box is not None and s.box.error is not None]
        for slot in failed:
            slot.box.close()
            slot.box = boxes.Fallback(self.host, list(slot.messages))
        return bool(failed)

    def close(self) -> None:
        for slot in self._made:
            if slot.box is not None:
                slot.box.close()

    def stale(self) -> None:
        """Something changed that no box said: boxes that draw themselves look again when they are next shown."""
        self._epoch += 1

    # --- rows ---

    def _layout(self, box: Box, cols: int) -> tuple[int, list[str], list[bool]]:
        """A box's rows at this width, and which of them continue the line above (they were cut from one long line)."""
        try:
            if box.hooks.layout:
                rows = box.hooks.layout(cols)
                return cols, rows, [False] * len(rows)
            rows, joined = [], []
            for line in box.lines:
                cut = wrap(line, cols)
                rows += cut
                joined += [False] + [True] * (len(cut) - 1)
            return cols, rows, joined
        except Exception as e:
            box.error = e
            rows = boxes.Fallback(self.host, box.messages).lines
            return cols, rows, [False] * len(rows)

    def rows_for(self, slot: Slot, cols: int) -> list[str]:
        """The rows of this slot at this width, worked out if they are not already (or if the box said they changed)."""
        box = self.box_of(slot)
        stale = box.hooks.layout and box._epoch != self._epoch  # draws itself, and something changed that no box said
        if box._laid is None or box._laid[0] != cols or box._dirty or stale:
            box._laid, box._dirty, box._epoch = self._layout(box, cols), False, self._epoch
        return box._laid[1]

    def joined_for(self, slot: Slot, cols: int) -> list[bool]:
        self.rows_for(slot, cols)
        return slot.box._laid[2]

    # --- places in the log ---

    def _index(self, anchor: Slot | None) -> int | None:
        try:
            return self.slots.index(anchor)  # a scan in C, comparing by identity
        except ValueError:
            return None

    def end_position(self, count: int, cols: int) -> tuple[Slot | None, int]:
        """The anchor that puts the last row of the log at the bottom of a screen of ``count`` rows."""
        need = count
        for i in range(len(self.slots) - 1, -1, -1):
            height = len(self.rows_for(self.slots[i], cols))
            if height >= need:
                return self.slots[i], height - need
            need -= height
        return (self.slots[0], 0) if self.slots else (None, 0)

    def move(self, anchor: Slot | None, offset: int, delta: int, count: int, cols: int) -> tuple[Slot | None, int, bool]:
        """Scroll from this anchor by ``delta`` rows (negative: up). Returns the new anchor and whether it is the end of the log."""
        i = self._index(anchor)
        if i is None:
            return (*self.end_position(count, cols), True)
        offset += delta
        if delta < 0:
            while offset < 0 and i > 0:
                i -= 1
                offset += len(self.rows_for(self.slots[i], cols))
            offset = max(offset, 0)
        else:
            while i < len(self.slots) - 1 and offset >= (height := len(self.rows_for(self.slots[i], cols))):
                offset -= height
                i += 1
        end, end_offset = self.end_position(count, cols)
        if end is not None and (i, offset) >= (self._index(end), end_offset):
            return end, end_offset, True
        return self.slots[i], offset, False

    def window(self, anchor: Slot | None, offset: int, count: int, cols: int) -> Window:
        """The ``count`` rows from this anchor, laying out only the slots they come from."""
        rows: list[str] = []
        places: list[Place] = []
        i = self._index(anchor)
        i = 0 if i is None else i
        while len(rows) < count and i < len(self.slots):
            slot = self.slots[i]
            have = self.rows_for(slot, cols)
            offset = min(offset, max(len(have) - 1, 0))
            places.append(Place(slot, slot.box, len(rows) - offset, len(have)))
            rows += have[offset : offset + count - len(rows)]
            offset, i = 0, i + 1
        at_end = i >= len(self.slots) and len(rows) <= count
        return Window(rows + [""] * (count - len(rows)), places, at_end)
