"""core/writer.py: Writer, the only way to change a log."""

import asyncio
from typing import IO, TYPE_CHECKING

from llvim.core.git import LLVIM, Author, Commit
from llvim.core.handoff import Offer
from llvim.core.live import record
from llvim.core.queue import Request, Wake
from llvim.core.watch import Watch

if TYPE_CHECKING:
    from llvim.core.log import Log


class Moved(Exception):
    """The head is not where the writer's writes start from, so committing would drop a commit."""


class Released(Exception):
    """The writer was released: it no longer holds the log."""


class Committing(Exception):
    """A commit of this writer is running, and what was asked would change what it writes."""


class Writer:
    """Got from `await Log.claim(...)`; `async with` it to release on leaving. Writes are uncommitted until commit();
    readers see them live.
    On release or death, what is uncommitted is discarded."""

    def __init__(self, log: "Log", key: str, request: Request, ticket: IO[bytes]):
        self._log, self._key, self._request, self._ticket = log, key, request, ticket
        self._base = log.head()
        self._messages, self._next, self._where = log._contents(self._base)
        self._saved_next = self._next
        self._dirty: set[int] = set()
        self._committing = False
        self._journal = self._start_journal()
        self._waiters: Wake | None = None

    def append(self, content: bytes) -> int:
        id = self._next
        self._change(b"S", id, content)
        self._next += 1
        return id

    def extend(self, id: int, chunk: bytes) -> None:
        self._change(b"E", id, chunk)

    def replace(self, id: int, content: bytes) -> None:
        if id not in self._messages:
            raise KeyError(id)
        self._change(b"S", id, content)

    def remove(self, id: int) -> None:
        self._change(b"D", id, b"")

    def restore(self, to: Commit) -> None:
        """Make the log look like `to` again, as a new uncommitted change on top. Not while a commit is being
        written."""
        self._check_held()
        if self._committing:
            raise Committing("a commit is being written")
        commit = self._log._resolve(to)
        restored, next_id, _ = self._log._contents(commit)
        base = self._log._contents(self._base)[0]
        self._dirty = {id for id in base.keys() | restored.keys() if base.get(id) != restored.get(id)}
        self._messages, self._next = restored, max(self._next, next_id)
        self._record(b"R", 0, commit.encode())

    async def commit(self, *, author: Author = LLVIM, message: str = "") -> Commit:
        """Make the writes permanent, as `author`'s. Raises Moved, keeping the writes, if something else moved the
        head, and GitError, also keeping them, if git would not commit or move it for another reason.
        Writes made while it runs are not in it; they stay uncommitted. Cancelled, it still waits for git to finish,
        since git may move the head anyway, and the writer must know where it is."""
        self._check_held()
        if self._committing:
            raise Committing("a commit is being written")
        if self._base is not None and not self._dirty and self._next == self._saved_next:
            return self._base
        dirty, self._dirty, next_id = self._dirty, set(), self._next
        self._committing = True
        changes = {id: self._messages.get(id) for id in dirty}
        git_step = asyncio.ensure_future(self._log._commit(self._base, changes, next_id, self._where, author, message))
        cancelled = False
        while not git_step.done():
            try:
                await asyncio.wait({git_step})
            except asyncio.CancelledError:
                cancelled = True
        self._committing = False
        commit = None if git_step.exception() else git_step.result()
        if commit is None:
            self._dirty |= dirty
        else:
            self._base, self._saved_next = commit, next_id
            if self._ticket is not None:
                self._journal.close()
                self._journal = self._start_journal()
                self._rewrite_late_changes()
        if cancelled:
            raise asyncio.CancelledError
        if commit is None:
            raise git_step.exception() or Moved(f"{self._log.ref} is no longer at {self._base}")
        return commit

    def outranked(self) -> bool:
        """Someone waiting has a higher priority. Yielding is the holder's choice."""
        _, waiting = self._log._queue.live()
        return bool(waiting) and waiting[0][1].priority > self._request.priority

    async def outranked_changed(self) -> None:
        """Return once `outranked()` may have changed since the last call. The first call returns at once: the watch
        starts then, so what changed before it is unknown."""
        self._check_held()
        if self._waiters is None:
            self._waiters = Wake(self._log._queue, Watch(self._log.dir, prefixes=("ticket.",)))
            return
        await self._waiters.changed()

    def offer(self) -> Offer:
        """Offer the log, still held, to another process: give it `offer.address`, and `await offer.taken()`. Once it
        is taken this writer is released, and what was uncommitted is discarded."""
        self._check_held()
        return Offer(self._key, self._ticket, self._hand_over)

    def release(self) -> None:
        if self._ticket is None:
            return
        self._log._queue.leave(self._key)
        self._hand_over()

    def _hand_over(self) -> None:
        """Stop being the holder, without ending the claim: the process that adopted it keeps it alive."""
        if self._waiters is not None:
            self._waiters.close()
        self._journal.close()
        self._ticket.close()
        self._ticket = None

    async def __aenter__(self) -> "Writer":
        return self

    async def __aexit__(self, *exc: object) -> None:
        self.release()

    def _check_held(self) -> None:
        if self._ticket is None:
            raise Released("this writer was released")

    def _change(self, op: bytes, id: int, payload: bytes) -> None:
        self._check_held()
        self._log._apply(self._messages, op, id, payload)
        self._dirty.add(id)
        self._record(op, id, payload)

    def _rewrite_late_changes(self) -> None:
        """Put the writes made while a commit ran into the fresh journal, as they stand against the new head."""
        for id in sorted(self._dirty):
            if id in self._messages:
                self._record(b"S", id, self._messages[id])
            elif id in self._where:
                self._record(b"D", id, b"")

    def _record(self, op: bytes, id: int, payload: bytes) -> None:
        self._journal.write(record(op, id, payload))
        self._journal.flush()

    def _start_journal(self) -> IO[bytes]:
        path = self._log.dir / f"journal.{self._key}"
        unfinished = path.with_name(path.name + ".next")
        journal = open(unfinished, "wb")
        journal.write(record(b"B", 0, (self._base or "").encode()))
        journal.flush()
        unfinished.rename(path)
        return journal
