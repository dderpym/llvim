"""core/log.py: Log, a view of one message log: read it, watch it, claim it, fork it."""

import asyncio
import os
import threading
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from pathlib import Path

from llvim.core import git, handoff
from llvim.core.git import Author, Commit, GitError
from llvim.core.live import Contents, Snapshot, View, apply, ordered
from llvim.core.queue import Queue, Request, Wake
from llvim.core.watch import Watch
from llvim.core.writer import Writer

BUCKET = 500


def store() -> Path:
    if path := os.environ.get("LLVIM_STORE"):
        return Path(path)
    return Path.home() / ".llvim" / "sessions"


def flat(project: Path) -> str:
    """One folder name per absolute path, never the same for two: `/home/a-b/c` -> `home-a%2Db-c`."""
    if len(project.parts) < 2:
        raise ValueError(f"not a project folder: {project}")
    return "-".join(part.replace("%", "%25").replace("-", "%2D") for part in project.parts[1:])


class Log:
    def __init__(
        self,
        project: str | os.PathLike,
        name: str = "main",
        *,
        repo: str | os.PathLike | None = None,
        bucket: int = BUCKET,
    ):
        if not git.is_branch_name(name):
            raise ValueError(f"bad log name: {name!r}")
        self.project = Path(project).resolve()
        self.name, self.bucket = name, bucket
        self.repo = Path(repo).resolve() if repo is not None else store() / flat(self.project)
        self.ref = f"refs/heads/{name}"
        git.init(self.repo)
        self.dir = self.repo / "llvim" / name
        self.dir.mkdir(parents=True, exist_ok=True)
        self._queue = Queue(self.dir)
        self._objects = git.Objects(self.repo)
        self._lock = threading.RLock()
        self._tree: git.Tree | None = None
        self._view: View | None = None

    def head(self) -> Commit | None:
        return git.target(self.repo, self.ref)

    def read(self, at: Commit | None = None) -> Snapshot:
        """At a commit: exactly what it holds. With no `at`: the head plus the holder's uncommitted writes."""
        if at is not None:
            commit = self._resolve(at)
            return Snapshot(commit, tuple(ordered(self._read_tree(commit).contents)))
        with self._lock:
            return self._read_live().snapshot()

    async def changes(self) -> AsyncIterator[Snapshot]:
        """The log now, then again each time it may have changed. Changes made while you were busy come as one
        snapshot."""
        wake = Wake(self._queue, Watch(self.dir))
        try:
            while True:
                yield self.read()
                await wake.changed()
        finally:
            wake.close()

    async def claim(self, request: Request, timeout: float | None = None) -> Writer:
        """Wait your turn, then get the Writer. Awaited before `async with`: `async with await log.claim(r) as w`.
        TimeoutError after `timeout` seconds; 0 takes the log only if it is yours at once."""
        turns = Wake(self._queue, Watch(self.dir, prefixes=("ticket.", "held.")))
        try:
            key, ticket = self._queue.join(request)
            try:
                async with asyncio.timeout(timeout):
                    while (stored := self._queue.take_turn(key)) is None:
                        await turns.changed()
                return Writer(self, key, stored, ticket)
            except BaseException:
                self._queue.leave(key)
                ticket.close()
                raise
        finally:
            turns.close()

    async def adopt(self, address: str) -> Writer:
        """The Writer of a claim another process offered at `address` (`Writer.offer`). The log stays held throughout.
        ConnectionError if nothing is offered there, ValueError if the claim is not on this log."""
        key, ticket = await asyncio.to_thread(handoff.take, address)
        held = self._queue.held()
        if held is None or held[0] != key:
            ticket.close()
            raise ValueError(f"the claim offered at {address} does not hold {self.ref}")
        return Writer(self, key, held[1], ticket)

    def holder(self) -> Request | None:
        held = self._queue.held()
        return held[1] if held else None

    def queue(self) -> list[Request]:
        """The holder's request first, then the waiters', in the order they will get the log."""
        held, waiting = self._queue.live()
        return [request for _, request in ([held] if held else []) + waiting]

    async def fork(self, name: str, at: Commit | None = None) -> "Log":
        """A new log starting at `at` (default: head). FileExistsError if `name` has commits."""
        start = self.head() if at is None else self._resolve(at)
        if start is None:
            raise ValueError("an empty log has nothing to fork")
        log = Log(self.project, name, repo=self.repo, bucket=self.bucket)
        try:
            await git.move(self.repo, log.ref, start, None)
        except GitError:
            if log.head() is not None:
                raise FileExistsError(name) from None
            raise
        return log

    # Called by the Writer: it never touches git itself.

    def _contents(self, commit: Commit | None) -> tuple[Contents, int, dict[int, str]]:
        """Copies of the messages of a commit by id and of the bucket of each, and its next free id."""
        if commit is None:
            return {}, 0, {}
        tree = self._read_tree(commit)
        return dict(tree.contents), tree.next_id, dict(tree.where)

    def _apply(self, messages: Contents, op: bytes, id: int, payload: bytes) -> None:
        apply(messages, op, id, payload, self._contents_at)

    async def _commit(
        self,
        base: Commit | None,
        changes: dict[int, bytes | None],
        next_id: int,
        where: dict[int, str],
        author: Author,
        message: str,
    ) -> Commit | None:
        return await git.commit(self.repo, self.ref, base, changes, next_id, where, self.bucket, author, message)

    def _resolve(self, commit: Commit) -> Commit:
        found = self._objects.get(f"{commit}^{{commit}}") if commit and "\n" not in commit else None
        if found is None:
            raise ValueError(f"no such commit: {commit!r}")
        return found[0]

    # Reading, through a cache of the last commit read and of the live view on top of the head.

    def _read_tree(self, commit: Commit) -> git.Tree:
        with self._lock:
            if self._tree is None or self._tree.commit != commit:
                self._tree = git.Tree.read(self._objects, commit, self._tree)
            return self._tree

    def _contents_at(self, commit: Commit) -> Contents:
        return self._read_tree(commit).contents

    def _read_live(self) -> View:
        held = self._queue.held()
        journal_path = self.dir / f"journal.{held[0]}" if held else None
        try:
            journal = open(journal_path, "rb") if journal_path else None
        except FileNotFoundError:
            journal = None
        with journal or _nothing():
            identity = (held[0], os.fstat(journal.fileno()).st_ino) if journal else None
            head = self.head()
            view = self._view
            if view is None or view.head != head or view.journal != identity:
                view = self._view = View(head, identity, self._contents_at(head) if head else {})
            if journal:
                journal.seek(view.offset)
                view.take(journal.read(), self._contents_at)
            return view


@contextmanager
def _nothing() -> Iterator[None]:
    yield
