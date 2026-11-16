"""core/log.py: Log, a view of one message log stored in git, and the only code that touches git."""

import asyncio
import ctypes
import fcntl
import json
import os
import secrets
import struct
import subprocess
import sys
import threading
import time
import weakref
from collections.abc import AsyncIterator, Coroutine, Generator, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any

if TYPE_CHECKING:
    from llvim.core.writer import Writer

type Commit = str


@dataclass(frozen=True)
class Message:
    id: int  # never reused, even after a remove
    content: bytes


@dataclass(frozen=True)
class Snapshot:
    """A log as one read saw it. `uncommitted` and `removed` are measured against `head`, not replayed from the writes."""

    head: Commit | None
    messages: tuple[Message, ...]
    uncommitted: tuple[Message, ...] = ()  # in `messages`, new or different from the head
    removed: tuple[Message, ...] = ()  # in the head, as the head has them; gone from `messages`


@dataclass(frozen=True)
class Author:
    """Who a commit says wrote it. Git keeps no name or email with `<`, `>` or a line break in it."""

    name: str
    email: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip() or any(c in self.name for c in "<>\n") or any(c in self.email for c in ">\n"):
            raise ValueError(f"git cannot record the author {self.name!r} <{self.email!r}>")


LLVIM = Author("llvim", "llvim")


@dataclass(frozen=True)
class Request:
    """What a claimant tells the queue. It is stored as JSON, so `data` must be JSON-serializable."""

    priority: int  # higher goes first
    data: Any = None


RECORD = struct.Struct(">cQQ")  # op, message id, payload length
BUCKET = 500
GIT_SETTINGS = {
    "core.hooksPath": os.devnull,  # no hook runs, from the repo or anywhere
    "commit.gpgSign": "false",
    "gc.auto": "0",  # tidying is the log's (see _repack), not a side effect of some command
    "maintenance.auto": "false",
    "core.fsmonitor": "false",
}
PACKS = 50  # more packs than this, and a commit merges them in the background
LOOSE = 6700  # the same for loose objects, estimated as git gc does it: those in objects/17, times 256


def store() -> Path:
    if path := os.environ.get("LLVIM_STORE"):
        return Path(path)
    return Path.home() / ".llvim" / "sessions"


def flat(project: Path) -> str:
    """One folder name per absolute path, never the same for two: `/home/a-b/c` -> `home-a%2Db-c`."""
    if len(project.parts) < 2:
        raise ValueError(f"not a project folder: {project}")
    return "-".join(part.replace("%", "%25").replace("-", "%2D") for part in project.parts[1:])


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


class Log:
    def __init__(self, project: str | os.PathLike, name: str = "main", *, repo: str | os.PathLike | None = None, bucket: int = BUCKET):
        if subprocess.run(["git", "check-ref-format", f"refs/heads/{name}"], env=_git_env()).returncode:
            raise ValueError(f"bad log name: {name!r}")
        self.project = Path(project).resolve()
        self.name, self.bucket = name, bucket
        self.repo = Path(repo).resolve() if repo is not None else store() / flat(self.project)
        self.ref = f"refs/heads/{name}"
        if not (self.repo / "HEAD").exists():
            command = ["git", "init", "--bare", "-q", "--object-format=sha1", "--template=", str(self.repo)]
            subprocess.run(command, capture_output=True, check=True, env=_git_env())
        self.dir = self.repo / "llvim" / name
        self.dir.mkdir(parents=True, exist_ok=True)
        self._objects = _Objects(self.repo)
        self._lock = threading.RLock()
        self._tree: _Tree | None = None
        self._view: _View | None = None

    def head(self) -> Commit | None:
        try:
            return (self.repo / self.ref).read_text().strip()
        except FileNotFoundError:
            pass
        try:
            packed = (self.repo / "packed-refs").read_text().splitlines()
        except FileNotFoundError:
            return None
        return next((line.split()[0] for line in packed if line.endswith(f" {self.ref}")), None)

    def read(self, at: Commit | None = None) -> Snapshot:
        """At a commit: exactly what it holds. With no `at`: the head plus the holder's uncommitted writes."""
        if at is not None:
            commit = self._resolve(at)
            return Snapshot(commit, tuple(_ordered(self._read_tree(commit).contents)))
        with self._lock:
            return self._read_live().snapshot()

    async def changes(self) -> AsyncIterator[Snapshot]:
        """The log now, then again each time it may have changed. Changes made while you were busy come as one snapshot."""
        wake = _Wake(self, _Watch(self.dir))
        try:
            while True:
                yield self.read()
                await wake.changed()
        finally:
            await wake.close()

    def claim(self, request: Request, timeout: float | None = None) -> "_Claim":
        """Wait your turn, then get the Writer: `await` it, or `async with` it to release on leaving.
        TimeoutError after `timeout` seconds; 0 takes the log only if it is yours at once."""
        return _Claim(self._claim(request, timeout))

    async def _claim(self, request: Request, timeout: float | None) -> "Writer":
        from llvim.core.writer import Writer

        turns = _Wake(self, _Watch(self.dir, prefixes=("ticket.", "held.")))
        try:
            with self._mutex():
                key = self._next_key()
                ticket = self._enqueue(key, request)
            try:
                async with asyncio.timeout(timeout):
                    while (stored := self._take_turn(key)) is None:
                        await turns.changed()
                return Writer(self, key, stored, ticket)
            except BaseException:
                with self._mutex():
                    self._dismiss(key)
                ticket.close()
                raise
        finally:
            await turns.close()

    def holder(self) -> Request | None:
        held = self._held()
        return held[1] if held else None

    def queue(self) -> list[Request]:
        """The holder's request first, then the waiters', in the order they will get the log."""
        held, waiting = self._live()
        return [request for _, request in ([held] if held else []) + waiting]

    async def fork(self, name: str, at: Commit | None = None) -> "Log":
        """A new log starting at `at` (default: head). FileExistsError if `name` has commits."""
        start = self.head() if at is None else self._resolve(at)
        if start is None:
            raise ValueError("an empty log has nothing to fork")
        log = Log(self.project, name, repo=self.repo, bucket=self.bucket)
        try:
            await self._git("update-ref", "--stdin", input=f"create {log.ref} {start}\n".encode())
        except subprocess.CalledProcessError as error:
            if log.head() is not None:
                raise FileExistsError(name) from None
            raise _refused(log.ref, error) from error
        return log

    # Called by the Writer: the git side of writing.

    def _contents(self, commit: Commit | None) -> tuple[dict[int, bytes], int, dict[int, str]]:
        """Copies of the messages of a commit by id and of the bucket of each, and its next free id."""
        if commit is None:
            return {}, 0, {}
        tree = self._read_tree(commit)
        return dict(tree.contents), tree.next_id, dict(tree.where)

    def _apply(self, messages: dict[int, bytes], op: bytes, id: int, payload: bytes) -> None:
        match op:
            case b"S":
                messages[id] = payload
            case b"E":
                messages[id] += payload
            case b"D":
                del messages[id]
            case b"R":
                messages.clear()
                messages.update(self._read_tree(payload.decode()).contents)

    async def _commit(
        self, base: Commit | None, changes: dict[int, bytes | None], next_id: int, where: dict[int, str], author: Author, message: str
    ) -> Commit | None:
        """Commit `changes` (None: removed) on top of `base`, and move the head there if it is still `base`. None if it is not;
        RuntimeError if git would not move it for another reason, such as a lock file left by a git that died.

        `where` is the bucket of each message in `base`; on success it is updated to the new commit. The caller keeps it, so a
        commit costs the same however long the log is."""
        scratch = f"refs/llvim/scratch/{secrets.token_hex(8)}"
        when, text = f"{int(time.time())} +0000", message.encode()
        lines = [f"commit {scratch}", "mark :1", f"author {author.name} <{author.email}> {when}", f"committer {LLVIM.name} <{LLVIM.email}> {when}"]
        script = [line.encode() for line in lines] + [f"data {len(text)}".encode(), text]
        script += [f"from {base}".encode()] if base else []
        for id, content in changes.items():
            bucket = where.get(id, str(id // self.bucket * self.bucket))
            if content is not None:
                script += [f"M 100644 inline messages/{bucket}/{id}".encode(), f"data {len(content)}".encode(), content]
            elif id in where:
                script.append(f"D messages/{bucket}/{id}".encode())
        script += [b"M 100644 inline next", f"data {len(str(next_id))}".encode(), str(next_id).encode()]
        script += [b"get-mark :1", b""]
        commit = (await self._git("fast-import", "--quiet", input=b"\n".join(script))).decode().strip()
        move = f"update {self.ref} {commit} {base}" if base else f"create {self.ref} {commit}"
        try:
            await self._git("update-ref", "--stdin", input=f"{move}\ndelete {scratch}\n".encode())
        except subprocess.CalledProcessError as error:
            with suppress(subprocess.CalledProcessError):
                await self._git("update-ref", "-d", scratch)
            if self.head() != base:
                return None
            raise _refused(self.ref, error) from error
        for id, content in changes.items():
            if content is None:
                where.pop(id, None)
            else:
                where.setdefault(id, str(id // self.bucket * self.bucket))
        if _untidy(self.repo):
            threading.Thread(target=_repack, args=(self.repo,), daemon=True).start()
        return commit

    def _resolve(self, commit: Commit) -> Commit:
        found = self._objects.get(f"{commit}^{{commit}}") if commit and "\n" not in commit else None
        if found is None:
            raise ValueError(f"no such commit: {commit!r}")
        return found[0]

    # Reading, through a cache of the last commit read and of the live view on top of the head.

    def _read_tree(self, commit: Commit) -> "_Tree":
        with self._lock:
            if self._tree is not None and self._tree.commit == commit:
                return self._tree
            self._tree = _Tree.read(self._objects, commit, self._tree)
            return self._tree

    def _read_live(self) -> "_View":
        held = self._held()
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
                contents = self._read_tree(head).contents if head else {}
                view = self._view = _View(head, identity, contents)
            if journal:
                journal.seek(view.offset)
                view.take(self, journal.read())
            return view

    async def _git(self, *args: str, input: bytes | None = None) -> bytes:
        command = ["git", "--git-dir", str(self.repo), *args]
        pipe = subprocess.PIPE
        process = await asyncio.create_subprocess_exec(*command, stdin=pipe, stdout=pipe, stderr=pipe, env=_git_env())
        out, err = await process.communicate(input)
        if process.returncode:
            raise subprocess.CalledProcessError(process.returncode, command, out, err)
        return out

    # Claims: the files of the holder and the waiters.

    def _held(self) -> tuple[str, Request] | None:
        for name in os.listdir(self.dir):
            if name.startswith("held.") and (request := _request_if_alive(self.dir / name)) is not None:
                return name.removeprefix("held."), request
        return None

    def _live(self) -> tuple[tuple[str, Request] | None, list[tuple[str, Request]]]:
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

    def _take_turn(self, key: str) -> Request | None:
        with self._mutex():
            self._reap()
            held, waiting = self._live()
            if held is not None or waiting[0][0] != key:
                return None
            (self.dir / f"ticket.{key}").rename(self.dir / f"held.{key}")
            return waiting[0][1]

    def _reap(self) -> None:
        for path in self.dir.iterdir():
            if path.name.startswith(_CLAIMS) and _request_if_alive(path) is None:
                self._dismiss(path.name.partition(".")[2])

    def _dismiss(self, key: str) -> None:
        for name in (f"new.{key}", f"ticket.{key}", f"held.{key}", f"journal.{key}", f"journal.{key}.next"):
            (self.dir / name).unlink(missing_ok=True)


_CLAIMS = ("new.", "ticket.", "held.")


def _refused(ref: str, error: subprocess.CalledProcessError) -> RuntimeError:
    return RuntimeError(f"git would not move {ref}: {error.stderr.decode(errors='replace').strip()}")


def _git_env() -> dict[str, str]:
    """The environment of every git llvim runs: none of the user's GIT_ variables or config files, and GIT_SETTINGS."""
    env = {name: value for name, value in os.environ.items() if not name.startswith("GIT_")}
    env |= {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0"}
    env["GIT_CONFIG_COUNT"] = str(len(GIT_SETTINGS))
    for i, (key, value) in enumerate(GIT_SETTINGS.items()):
        env[f"GIT_CONFIG_KEY_{i}"], env[f"GIT_CONFIG_VALUE_{i}"] = key, value
    return env


class _Claim(Coroutine[Any, Any, "Writer"]):
    """A claim in progress: a coroutine giving the Writer (so a task can run it), and `async with` also releases it on leaving."""

    def __init__(self, claiming: Coroutine[Any, Any, "Writer"]):
        self._claiming, self._writer = claiming, None

    def __await__(self) -> Generator[Any, None, "Writer"]:
        return self._claiming.__await__()

    def send(self, value: Any) -> Any:
        return self._claiming.send(value)

    def throw(self, *args: Any) -> Any:
        return self._claiming.throw(*args)

    def close(self) -> None:
        self._claiming.close()

    async def __aenter__(self) -> "Writer":
        self._writer = await self._claiming
        return self._writer

    async def __aexit__(self, *exc: object) -> None:
        self._writer.release()


@contextmanager
def _nothing() -> Iterator[None]:
    yield


def _ordered(contents: dict[int, bytes]) -> list[Message]:
    return [Message(id, contents[id]) for id in sorted(contents)]


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


class _Objects:
    """One `git cat-file --batch` kept running, so reading an object is a pipe round trip, not a new process."""

    def __init__(self, repo: Path):
        self._repo, self._process, self._lock = repo, None, threading.Lock()

    def get(self, name: str) -> tuple[str, bytes] | None:
        """The id and content of the object `name` names, or None."""
        with self._lock:
            if self._process is None:
                command = ["git", "--git-dir", str(self._repo), "cat-file", "--batch"]
                pipe = subprocess.PIPE
                self._process = subprocess.Popen(command, stdin=pipe, stdout=pipe, stderr=subprocess.DEVNULL, env=_git_env())
                weakref.finalize(self, _stop, self._process)
            self._process.stdin.write(name.encode() + b"\n")
            self._process.stdin.flush()
            header = self._process.stdout.readline().split()
            if len(header) != 3:
                return None
            content = self._process.stdout.read(int(header[2]) + 1)[:-1]
            return header[0].decode(), content


def _stop(process: subprocess.Popen) -> None:
    process.stdin.close()
    process.wait()
    process.stdout.close()


def _entries(tree: bytes) -> Iterator[tuple[str, str]]:
    """The names and object ids in a raw git tree."""
    at = 0
    while at < len(tree):
        nul = tree.index(b"\0", at)
        yield tree[tree.index(b" ", at) + 1 : nul].decode(), tree[nul + 1 : nul + 21].hex()
        at = nul + 21


@dataclass
class _Tree:
    """A commit's messages, read bucket by bucket: a bucket whose tree did not change since the last read is not read again."""

    commit: Commit
    next_id: int
    buckets: dict[str, tuple[str, dict[int, tuple[str, bytes]]]]  # name: (tree id, {message id: (blob id, content)})
    contents: dict[int, bytes]
    where: dict[int, str]  # message id: its bucket

    @classmethod
    def read(cls, objects: _Objects, commit: Commit, last: "_Tree | None") -> "_Tree":
        def content(name: str) -> bytes:
            found = objects.get(name)
            assert found is not None, f"{name} is missing from the repo"
            return found[1]

        root = dict(_entries(content(content(commit)[5:45].decode())))
        buckets = {}
        for bucket, tree in _entries(content(root["messages"])) if "messages" in root else ():
            known = last.buckets.get(bucket) if last else None
            if known and known[0] == tree:
                buckets[bucket] = known
                continue
            blobs = {blob: text for blob, text in known[1].values()} if known else {}
            entries = _entries(content(tree))
            buckets[bucket] = (tree, {int(id): (blob, blobs[blob] if blob in blobs else content(blob)) for id, blob in entries})
        contents, where = {}, {}
        for bucket, (_, messages) in buckets.items():
            for id, (_, text) in messages.items():
                contents[id], where[id] = text, bucket
        return cls(commit, int(content(root["next"])), buckets, contents, where)


class _View:
    """The head plus the holder's journal, kept between reads: a read applies only the records written since the last one."""

    def __init__(self, head: Commit | None, journal: tuple[str, int] | None, contents: dict[int, bytes]):
        self.head, self.journal, self._base, self.contents = head, journal, contents, dict(contents)
        self.offset, self.applies, self._ordered, self._snapshot = 0, False, None, None
        self._index: dict[int, int] = {}
        self._touched: set[int] = set()

    def take(self, log: Log, data: bytes) -> None:
        for op, id, payload in records(data):
            self.offset += RECORD.size + len(payload)
            if op == b"B":
                self.applies = (payload.decode() or None) == self.head
            elif self.applies:
                self._touched.update(self.contents if op == b"R" else (id,))
                log._apply(self.contents, op, id, payload)
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
                self._ordered = _ordered(self.contents)
                self._index = {message.id: i for i, message in enumerate(self._ordered)}
            touched, now, base = sorted(self._touched), self.contents, self._base
            uncommitted = tuple(Message(id, now[id]) for id in touched if id in now and base.get(id) != now[id])
            removed = tuple(Message(id, base[id]) for id in touched if id not in now and id in base)
            self._snapshot = Snapshot(self.head, tuple(self._ordered), uncommitted, removed)
        return self._snapshot


def _untidy(repo: Path) -> bool:
    """Too many packs or loose objects. fast-import leaves a pack per commit, or loose objects for a small one."""
    try:
        loose = len(os.listdir(repo / "objects" / "17")) * 256
    except FileNotFoundError:
        loose = 0
    return loose > LOOSE or len(list((repo / "objects" / "pack").glob("*.pack"))) > PACKS


def _repack(repo: Path) -> None:
    """Merge the packs fast-import leaves, one per commit. One repack at a time; a commit that finds one running skips it."""
    with open(repo / "llvim" / "repack.lock", "wb") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        subprocess.run(["git", "--git-dir", str(repo), "repack", "-d", "-q", "--geometric=2"], capture_output=True, env=_git_env())


class _Wake:
    """Waits for the next event in a log's folder, or for the holder's lock to be let go, whichever is first.

    The kernel sends the close event of a dying process before it lets go of its locks, so a waiter woken by the close can still
    find the holder alive, and no event follows. A thread blocked on a shared lock of the holder's file is woken exactly then."""

    def __init__(self, log: Log, watch: "_Watch"):
        self._log, self._watch, self._unlocked = log, watch, None
        self._held = self._holder_now()

    def _holder_now(self) -> str | None:
        """The holder's key, watching its lock from now on. Made before the caller reads, so a death after it is never missed."""
        held = self._log._held()
        key = held[0] if held else None
        self._unlocked = _unlocked(self._log.dir / f"held.{key}") if key else None
        return key

    async def changed(self) -> None:
        if (self._log._held() or (None,))[0] != self._held:
            self._held = self._holder_now()
            return
        event = asyncio.ensure_future(self._watch.changed())
        await asyncio.wait({event} | ({self._unlocked} if self._unlocked else set()), return_when=asyncio.FIRST_COMPLETED)
        if self._unlocked and self._unlocked.done():
            self._held = self._holder_now()
        if not event.done():
            event.cancel()
            await asyncio.wait({event})

    async def close(self) -> None:
        self._watch.close()


def _unlocked(path: Path) -> asyncio.Future:
    """Done once nobody holds the lock of `path`. The thread is a daemon, so a program can exit while a holder lives on."""
    loop, future = asyncio.get_running_loop(), asyncio.get_running_loop().create_future()

    def wait() -> None:
        try:
            with open(path, "rb") as held:
                fcntl.flock(held, fcntl.LOCK_SH)
        except FileNotFoundError:
            pass
        try:
            loop.call_soon_threadsafe(_settle, future)
        except RuntimeError:
            pass  # the loop has closed

    threading.Thread(target=wait, daemon=True).start()
    return future


def _settle(future: asyncio.Future) -> None:
    if not future.done():
        future.set_result(None)


_IN_MODIFY, _IN_CLOSE_WRITE, _IN_MOVED_FROM, _IN_MOVED_TO, _IN_CREATE, _IN_DELETE = 0x2, 0x8, 0x40, 0x80, 0x100, 0x200
_IN_Q_OVERFLOW = 0x4000
_EVENTS = _IN_MODIFY | _IN_CLOSE_WRITE | _IN_MOVED_FROM | _IN_MOVED_TO | _IN_CREATE | _IN_DELETE
_EVENT = struct.Struct("iIII")  # wd, mask, cookie, name length
_libc = ctypes.CDLL(None, use_errno=True) if sys.platform == "linux" else None


class _Watch:
    """Inotify on one directory, wanting only events on names with one of `prefixes`."""

    def __init__(self, directory: Path, prefixes: tuple[str, ...] = ("",)):
        if _libc is None:
            raise NotImplementedError("llvim waits with inotify, which only Linux has")
        fd = _libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
        if fd < 0:
            raise OSError(ctypes.get_errno(), "inotify_init1")
        self._fd, self._prefixes = fd, prefixes
        self.close = weakref.finalize(self, os.close, fd)
        if _libc.inotify_add_watch(fd, os.fsencode(directory), _EVENTS) < 0:
            errno = ctypes.get_errno()
            self.close()
            raise OSError(errno, "inotify_add_watch", str(directory))

    async def changed(self) -> None:
        """Return once a wanted event has come since the last call."""
        loop = asyncio.get_running_loop()
        while not self._drain():
            readable = loop.create_future()
            loop.add_reader(self._fd, _settle, readable)
            try:
                await readable
            finally:
                loop.remove_reader(self._fd)

    def _drain(self) -> bool:
        wanted = False
        while True:
            try:
                data = os.read(self._fd, 65536)
            except BlockingIOError:
                return wanted
            at = 0
            while at < len(data):
                _, mask, _, size = _EVENT.unpack_from(data, at)
                name = os.fsdecode(data[at + _EVENT.size : at + _EVENT.size + size].rstrip(b"\0"))
                wanted = wanted or bool(mask & _IN_Q_OVERFLOW) or name.startswith(self._prefixes)
                at += _EVENT.size + size
