import asyncio
import contextlib
import hashlib
import inspect
import shutil
import subprocess
from pathlib import Path

import pytest

from llvim.core import LLVIM, GitError, Message, Request, Snapshot
from llvim.std.conversation import Entry, encode
from llvim.std.panels.logviewer.box import Host


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem):
    """Run an `async def` test in a fresh event loop, so async code needs no pytest plugin."""
    if not inspect.iscoroutinefunction(pyfuncitem.obj):
        return None
    arguments = {name: pyfuncitem.funcargs[name] for name in pyfuncitem._fixtureinfo.argnames}
    asyncio.run(pyfuncitem.obj(**arguments))
    return True


@pytest.fixture(autouse=True)
def outside_tmux(monkeypatch):
    """Every test runs as if it were not in a tmux pane, whatever the developer's terminal is: panels would otherwise find
    their panes."""
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("TMUX_PANE", raising=False)


@pytest.fixture
def entry():
    """Make an entry, each with a new id: `entry(["user"], "hi", model="m")`; `streaming=True` for one still arriving."""
    ids = iter(range(1_000_000))

    def make(tags, content: str = "", streaming: bool = False, **extra) -> Entry:
        return Entry(next(ids), list(tags), content, extra, streaming, streaming)

    return make


# --- a log, in memory ---


class FakeWriter:
    """The Writer a FakeLog hands out. Its writes go straight into the log's uncommitted state."""

    def __init__(self, log: "FakeLog", request: Request):
        self._log, self._request, self._released = log, request, False
        self._waiting_seen: list[Request] | None = None

    def append(self, content: bytes) -> int:
        id = self._log._new_id()
        self._log._set(id, content)
        return id

    def extend(self, id: int, chunk: bytes) -> None:
        self._log._set(id, self._log._live[id] + chunk)

    def replace(self, id: int, content: bytes) -> None:
        if id not in self._log._live:
            raise KeyError(id)
        self._log._set(id, content)

    def remove(self, id: int) -> None:
        del self._log._live[id]
        self._log.version += 1

    async def commit(self, *, author=LLVIM, message: str = "") -> str:
        log = self._log
        if log._commits and log._live == log._committed():
            return log.head()
        sha = f"{len(log._commits) + 1:040x}"
        log._commits.append((sha, dict(log._live)))
        log.authors.append(author)
        log.version += 1
        return sha

    def outranked(self) -> bool:
        return any(request.priority > self._request.priority for request in self._waiting())

    async def outranked_changed(self) -> None:
        if self._waiting_seen is not None:
            while self._waiting() == self._waiting_seen:
                await asyncio.sleep(0.001)
        self._waiting_seen = self._waiting()

    def _waiting(self) -> list[Request]:
        """Who waits: those a test set, and those in `claim`."""
        return self._log.waiting + [request for _, request in self._log._waiters]

    def offer(self) -> "FakeOffer":
        return FakeOffer(self)

    def release(self) -> None:
        if not self._released:
            self._released = True
            self._log._live, self._log._holder = None, None
            self._log.version += 1

    async def __aenter__(self) -> "FakeWriter":
        return self

    async def __aexit__(self, *exc) -> None:
        self.release()


class FakeOffer:
    """A FakeWriter's claim, offered: `FakeLog.adopt(offer.address)` takes it, and the log stays held."""

    def __init__(self, writer: FakeWriter):
        self.writer, self.address, self.adopted = writer, f"offer-{id(writer)}", False
        writer._log.offers[self.address] = self

    async def taken(self, timeout: float | None = None) -> None:
        try:
            async with asyncio.timeout(timeout):
                while not self.adopted:
                    await asyncio.sleep(0.001)
        finally:
            self.close()

    def close(self) -> None:
        self.writer._log.offers.pop(self.address, None)


class FakeLog:
    """The calls of `llvim.core.Log` that std uses, in memory, and helpers that put it in the state a test needs:
    `say` (a committed message), `ask` (a user message and a cue for the model), `write` (an uncommitted one), `hold` (someone
    else holds the log), `waiting` (who waits). `tests/core/test_log.py` checks it has no call the real log lacks.
    Blobs and trees are kept in memory. A blob's id is git's, since a caller may work one out itself; a tree's is not."""

    name = "main"

    def __init__(self, dir: Path | None = None):
        self.project = Path.cwd()
        self.dir = dir
        self._blobs: dict[str, bytes] = {}
        self._trees: dict[str, dict[str, tuple[str, str]]] = {}
        self._commits: list[tuple[str, dict[int, bytes]]] = []
        self._live: dict[int, bytes] | None = None
        self._next = 0
        self._holder: Request | None = None
        self.waiting: list[Request] = []  # set by a test: who waits, besides those in `claim`
        self._waiters: list[tuple[int, Request]] = []
        self.claims: list[Request] = []
        self.offers: dict[str, FakeOffer] = {}
        self.authors: list = []
        self.version = 0  # raised by every change, which is how `changes` notices one

    def head(self) -> str | None:
        return self._commits[-1][0] if self._commits else None

    def read(self, at: str | None = None) -> Snapshot:
        if at is not None:
            contents = dict(self._commits)[at]
            return Snapshot(at, tuple(Message(id, contents[id]) for id in sorted(contents)))
        base = self._committed()
        now = base if self._live is None else self._live
        return Snapshot(
            self.head(),
            tuple(Message(id, now[id]) for id in sorted(now)),
            tuple(Message(id, now[id]) for id in sorted(now) if base.get(id) != now[id]),
            tuple(Message(id, base[id]) for id in sorted(base) if id not in now),
        )

    async def changes(self):
        while True:
            seen = self.version
            yield self.read()
            while self.version == seen:
                await asyncio.sleep(0.001)

    async def claim(self, request: Request, timeout: float | None = None) -> FakeWriter:
        """As core's: the log goes to the waiter of highest priority, then the first to arrive, once nobody holds it."""
        self.claims.append(request)
        ticket = (len(self.claims), request)
        self._waiters.append(ticket)
        try:
            async with asyncio.timeout(timeout):
                while (
                    self._holder is not None or min(self._waiters, key=lambda w: (-w[1].priority, w[0])) is not ticket
                ):
                    await asyncio.sleep(0.001)
        finally:
            self._waiters.remove(ticket)
        self._holder, self._live = request, dict(self._committed())
        self.version += 1
        return FakeWriter(self, request)

    async def adopt(self, address: str) -> FakeWriter:
        """As core's: the writer of the claim offered there, the giver's released without the log coming free."""
        if address not in self.offers:
            raise ConnectionError(f"no claim is offered at {address}")
        offer = self.offers[address]
        offer.writer._released, offer.adopted = True, True
        self._live = dict(self._committed())
        self.version += 1
        return FakeWriter(self, offer.writer._request)

    def holder(self) -> Request | None:
        return self._holder

    def write_blobs(self, sources) -> list[str]:
        ids = []
        for source in sources:
            content = source if isinstance(source, bytes) else Path(source).read_bytes()
            id = hashlib.sha1(b"blob %d\0" % len(content) + content).hexdigest()
            self._blobs[id] = content
            ids.append(id)
        return ids

    def blob(self, id: str) -> bytes:
        if id not in self._blobs:
            raise ValueError(f"no such blob: {id!r}")
        return self._blobs[id]

    def write_tree(self, entries: dict[str, tuple[str, str]]) -> str | None:
        flat = {}
        for path, (mode, id) in entries.items():
            if mode == "040000":
                flat |= {f"{path}/{inside}": entry for inside, entry in self.read_tree(id).items()}
            elif id in self._blobs:
                flat[path] = (mode, id)
            else:
                raise GitError("git would not make a tree", f"{id} is missing")
        if not flat:
            return None
        id = hashlib.sha1(repr(sorted(flat.items())).encode()).hexdigest()
        self._trees[id] = flat
        return id

    def read_tree(self, id: str) -> dict[str, tuple[str, str]]:
        if id not in self._trees:
            raise ValueError(f"no such tree: {id!r}")
        return dict(self._trees[id])

    def queue(self) -> list[Request]:
        waiting = self.waiting + [request for _, request in sorted(self._waiters, key=lambda w: w[0])]
        return ([self._holder] if self._holder else []) + sorted(waiting, key=lambda r: -r.priority)

    # --- helpers that set a state up ---

    def say(self, tags, content: str = "", **extra) -> int:
        """A committed message."""
        id = self._new_id()
        self._commits.append(
            (f"{len(self._commits) + 1:040x}", self._committed() | {id: encode(tags, content, **extra)})
        )
        self.version += 1
        return id

    def ask(self, content: str = "hi") -> None:
        """A committed user message, and the cue the input bar leaves with it."""
        self.say(["user"], content)
        self.say(["cue", "generate"])

    def write(self, tags, content: str = "", **extra) -> int:
        """An uncommitted message, as if a holder had written it."""
        if self._live is None:
            self._live = dict(self._committed())
        id = self._new_id()
        self._set(id, encode(tags, content, **extra))
        return id

    def hold(self, request: Request | None = Request(0, "someone")) -> None:
        """Someone else holds the log (None: nobody does)."""
        self._holder = request
        if request is None:
            self._live = None
        self.version += 1

    def _new_id(self) -> int:
        id, self._next = self._next, self._next + 1
        return id

    def _committed(self) -> dict[int, bytes]:
        return self._commits[-1][1] if self._commits else {}

    def _set(self, id: int, content: bytes) -> None:
        self._live[id] = content
        self.version += 1


@pytest.fixture
def fake_log(tmp_path) -> FakeLog:
    """A log in memory, standing in for `llvim.core.Log`. Its folder is empty and private to the test."""
    return FakeLog(tmp_path / "log")


# --- the viewer's side: a host and a screen ---


class StubHost(Host):
    """A host that starts nothing and remembers what said it changed."""

    live = False
    cols = 80

    def __init__(self):
        self.changes: list = []

    def changed(self, box=None):
        self.changes.append(box)


@pytest.fixture
def stub_host() -> StubHost:
    """A Host for boxes, which starts nothing."""
    return StubHost()


class StubScreen:
    """Enough of a screen for a panel: a size, input a test queues, and a note of what was copied and drawn."""

    def __init__(self, cols=40, rows=12):
        self.cols, self.rows, self.copied, self.drawn, self.events = cols, rows, [], [], []
        self.resized, self.invalidated = False, 0

    def size(self):
        return self.cols, self.rows

    def fds(self):
        return []

    def read(self):
        events, self.events = self.events, []
        return events

    def copy(self, text):
        self.copied.append(text)

    def draw(self, rows, cursor=None):
        self.drawn.append((rows, cursor))

    def invalidate(self):
        self.invalidated += 1

    def cbreak(self):
        return contextlib.nullcontext()


@pytest.fixture
def stub_screen() -> StubScreen:
    """A Screen that draws nowhere."""
    return StubScreen()


# --- the panes of a layout, as keys.Panes finds them ---


class FakeTmux:
    """Answers the pane lookups of `Panes` from a dict, and records every command it is given."""

    def __init__(self, ids=None):
        self.ids, self.commands = ids or {}, []

    def __call__(self, args):
        self.commands.append(args)
        return self.ids.get(args[-1].removeprefix("@llvim_pane_"), "") + "\n" if args[0] == "show-options" else ""

    @property
    def sent(self):
        """What was sent to other panes: `[(pane, bytes)]`."""
        return [(c[2], bytes(int(h, 16) for h in c[4:])) for c in self.commands if c[0] == "send-keys"]

    @property
    def focused(self):
        return [c[2] for c in self.commands if c[0] == "select-pane"]


@pytest.fixture
def layout():
    """`layout(input="%3")` gives `(panes, tmux)`: this panel is `%1`, the named panels are where they say, and `tmux`
    records what was done."""
    from llvim.std.panels.keys import Panes

    def make(**ids):
        tmux = FakeTmux(ids)
        return Panes(tmux, here="%1"), tmux

    return make


# --- tmux: a real server, for the few tests that need one ---


def pytest_collection_modifyitems(config, items):
    """Tests marked `needs_tmux` are skipped where there is no tmux."""
    if shutil.which("tmux"):
        return
    skip = pytest.mark.skip(reason="needs tmux")
    for item in items:
        if "needs_tmux" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def tmux_server(tmp_path):
    """A tmux server of its own with one session, `s`. Yields `(tmux, socket_path)`; `tmux(*args)` runs a command."""
    sock = f"llvimtest{tmp_path.name[-8:]}"

    def tmux(*args):
        return subprocess.run(["tmux", "-L", sock, *args], capture_output=True, text=True).stdout

    tmux.sock = sock
    tmux("-f", "/dev/null", "new-session", "-d", "-x", "100", "-y", "30", "-s", "s", "sleep 600")
    yield tmux, tmux("display-message", "-p", "#{socket_path}").strip()
    tmux("kill-server")
