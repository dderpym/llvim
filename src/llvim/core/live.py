"""core/live.py: the journal of uncommitted writes, and View, the head with a journal applied."""

import struct
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from llvim.core.git import Commit

RECORD = struct.Struct(">cQQ")  # op, message id, payload length
FILE_OPS = (b"F", b"T")  # a file or folder put under files/: "path\0object id", no id for a removal; not for readers

type Contents = dict[int, bytes]


@dataclass(frozen=True)
class Message:
    id: int  # never reused, even after a remove
    content: bytes


@dataclass(frozen=True)
class Snapshot:
    """A log as one read saw it. `uncommitted` and `removed` are measured against `head`, not replayed from the
    writes."""

    head: Commit | None
    messages: tuple[Message, ...]
    uncommitted: tuple[Message, ...] = ()  # in `messages`, new or different from the head
    removed: tuple[Message, ...] = ()  # in the head, as the head has them; gone from `messages`


def record(op: bytes, id: int, payload: bytes) -> bytes:
    return RECORD.pack(op, id, len(payload)) + payload


def records(journal: bytes) -> Iterator[tuple[bytes, int, bytes]]:
    """The whole records of a journal; one still being written is left out."""
    at = 0
    while at + RECORD.size <= len(journal):
        op, id, size = RECORD.unpack_from(journal, at)
        start = at + RECORD.size
        if start + size > len(journal):
            return
        yield op, id, journal[start : start + size]
        at = start + size


def apply(messages: Contents, op: bytes, id: int, payload: bytes, contents_at: Callable[[Commit], Contents]) -> None:
    """Apply one record. The Writer and readers both use it, so they cannot disagree on what a journal means."""
    match op:
        case b"S":
            messages[id] = payload
        case b"E":
            messages[id] += payload
        case b"D":
            del messages[id]
        case b"R":
            messages.clear()
            messages.update(contents_at(payload.decode()))


def ordered(contents: Contents) -> list[Message]:
    return [Message(id, contents[id]) for id in sorted(contents)]


class View:
    """The head plus the holder's journal, kept between reads: a read applies only the records written since the last
    one."""

    def __init__(self, head: Commit | None, journal: tuple[str, int] | None, contents: Contents):
        self.head, self.journal, self._base, self.contents = head, journal, contents, dict(contents)
        self.offset, self.applies, self._ordered, self._snapshot = 0, False, None, None
        self._index: dict[int, int] = {}
        self._touched: set[int] = set()

    def take(self, data: bytes, contents_at: Callable[[Commit], Contents]) -> None:
        for op, id, payload in records(data):
            self.offset += RECORD.size + len(payload)
            if op == b"B":
                self.applies = (payload.decode() or None) == self.head
            elif self.applies and op not in FILE_OPS:
                self._touched.update(self.contents if op == b"R" else (id,))
                apply(self.contents, op, id, payload, contents_at)
                self._touched.update(self.contents if op == b"R" else ())
                self._update(op, id)
                self._snapshot = None

    def _update(self, op: bytes, id: int) -> None:
        if self._ordered is None:
            return
        if id in self._index and op in (b"S", b"E"):
            self._ordered[self._index[id]] = Message(id, self.contents[id])
        elif op == b"S" and (not self._ordered or id > self._ordered[-1].id):
            self._index[id] = len(self._ordered)
            self._ordered.append(Message(id, self.contents[id]))
        else:
            self._ordered = None

    def snapshot(self) -> Snapshot:
        if self._snapshot is None:
            if self._ordered is None:
                self._ordered = ordered(self.contents)
                self._index = {message.id: i for i, message in enumerate(self._ordered)}
            touched, now, base = sorted(self._touched), self.contents, self._base
            uncommitted = tuple(Message(id, now[id]) for id in touched if id in now and base.get(id) != now[id])
            removed = tuple(Message(id, base[id]) for id in touched if id not in now and id in base)
            self._snapshot = Snapshot(self.head, tuple(self._ordered), uncommitted, removed)
        return self._snapshot
