"""core/queue.py: Queue, the claims on one log as locked files, and Wake, which waits for the queue to move."""

import asyncio
import fcntl
import json
import os
import secrets
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

from llvim.core.watch import Watch, settle


@dataclass(frozen=True)
class Request:
    """What a claimant tells the queue. It is stored as JSON, so `data` must be JSON-serializable."""

    priority: int  # higher goes first
    data: Any = None


type Entry = tuple[str, Request]  # a claim's key and request

_CLAIMS = ("new.", "ticket.", "held.")


class Queue:
    """The claims in a log's folder. A claim is alive while its process holds the lock in its file."""

    def __init__(self, dir: Path):
        self.dir = dir

    def held(self) -> Entry | None:
        for name in os.listdir(self.dir):
            if name.startswith("held.") and (request := _request_if_alive(self.dir / name)) is not None:
                return name.removeprefix("held."), request
        return None

    def live(self) -> tuple[Entry | None, list[Entry]]:
        """The holder, and the waiters in the order they will get the log."""
        held, waiting = None, []
        for path in sorted(self.dir.iterdir()):
            kind, _, key = path.name.partition(".")
            if kind in ("held", "ticket") and (request := _request_if_alive(path)) is not None:
                if kind == "held":
                    held = (key, request)
                else:
                    waiting.append((key, request))
        waiting.sort(key=lambda entry: entry[1].priority, reverse=True)
        return held, waiting

    def join(self, request: Request) -> tuple[str, IO[bytes]]:
        """A new ticket at the back of the queue. It lives while the returned file stays open."""
        with self._mutex():
            key = self._next_key()
            return key, self._enqueue(key, request)

    def take_turn(self, key: str) -> Request | None:
        """Make `key` the holder if no one holds the log and it is first; its request if it did."""
        with self._mutex():
            self._reap()
            held, waiting = self.live()
            if held is not None or waiting[0][0] != key:
                return None
            (self.dir / f"ticket.{key}").rename(self.dir / f"held.{key}")
            return waiting[0][1]

    def leave(self, key: str) -> None:
        with self._mutex():
            self._dismiss(key)

    @contextmanager
    def _mutex(self) -> Iterator[None]:
        # Read-only, so taking it makes no close-write event to wake the watchers.
        fd = os.open(self.dir / "mutex", os.O_RDONLY | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def _next_key(self) -> str:
        seqs = [int(path.name.split(".")[1]) for path in self.dir.iterdir() if path.name.startswith(_CLAIMS)]
        return f"{max(seqs, default=0) + 1:012d}.{secrets.token_hex(4)}"

    def _enqueue(self, key: str, request: Request) -> IO[bytes]:
        content = json.dumps({"priority": request.priority, "data": request.data}).encode()
        new = self.dir / f"new.{key}"
        ticket = open(new, "xb")
        fcntl.flock(ticket, fcntl.LOCK_EX)
        ticket.write(content)
        ticket.flush()
        new.rename(self.dir / f"ticket.{key}")
        return ticket

    def _reap(self) -> None:
        for path in self.dir.iterdir():
            if path.name.startswith(_CLAIMS) and _request_if_alive(path) is None:
                self._dismiss(path.name.partition(".")[2])

    def _dismiss(self, key: str) -> None:
        for name in (f"new.{key}", f"ticket.{key}", f"held.{key}", f"journal.{key}", f"journal.{key}.next"):
            (self.dir / name).unlink(missing_ok=True)


def _request_if_alive(path: Path) -> Request | None:
    try:
        claim = open(path, "rb")
    except FileNotFoundError:
        return None
    with claim:
        try:
            fcntl.flock(claim, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            return Request(**json.loads(claim.read()))
        return None


class Wake:
    """Waits for the next event in a queue's folder, or for the holder's lock to be let go, whichever is first.

    The kernel sends the close event of a dying process before it lets go of its locks, so a waiter woken by the close
    can still find the holder alive, and no event follows. A thread blocked on a shared lock of the holder's file is
    woken exactly then."""

    def __init__(self, queue: Queue, watch: Watch):
        self._queue, self._watch, self._unlocked = queue, watch, None
        self._held = self._holder_now()

    def _holder_now(self) -> str | None:
        """The holder's key, watching its lock from now on. Made before the caller reads, so a death after it is never
        missed."""
        held = self._queue.held()
        key = held[0] if held else None
        self._unlocked = _unlocked(self._queue.dir / f"held.{key}") if key else None
        return key

    async def changed(self) -> None:
        if (self._queue.held() or (None,))[0] != self._held:
            self._held = self._holder_now()
            return
        event = asyncio.ensure_future(self._watch.changed())
        waits = {event} | ({self._unlocked} if self._unlocked else set())
        try:
            await asyncio.wait(waits, return_when=asyncio.FIRST_COMPLETED)
        finally:
            # Also when this wait is cancelled: a task left reading the watch would fail once it is closed.
            event.cancel()
            await asyncio.wait({event})
        if self._unlocked and self._unlocked.done():
            self._held = self._holder_now()

    def close(self) -> None:
        self._watch.close()


def _unlocked(path: Path) -> asyncio.Future:
    """Done once nobody holds the lock of `path`. The thread is a daemon, so a program can exit while a holder lives
    on."""
    loop = asyncio.get_running_loop()
    future = loop.create_future()

    def wait() -> None:
        try:
            with open(path, "rb") as held:
                fcntl.flock(held, fcntl.LOCK_SH)
        except FileNotFoundError:
            pass
        try:
            loop.call_soon_threadsafe(settle, future)
        except RuntimeError:
            pass  # the loop has closed

    threading.Thread(target=wait, daemon=True).start()
    return future
