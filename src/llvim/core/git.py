"""core/git.py: the repo of a project, and the only code that runs git or knows how a log is laid out in it."""

import asyncio
import fcntl
import os
import secrets
import subprocess
import tempfile
import threading
import time
import weakref
from collections.abc import Iterable, Iterator
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

type Commit = str
type FileChange = tuple[str, str] | None  # (mode, object id) of what goes at a path under files/; None removes it

EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


class GitError(Exception):
    """Git failed or refused. The message ends with git's own."""

    def __init__(self, what: str, stderr: str):
        self.stderr = stderr.strip()
        super().__init__(f"{what}: {self.stderr}")


@dataclass(frozen=True)
class Author:
    """Who a commit says wrote it. Git keeps no name or email with `<`, `>`, a line break or a NUL in it."""

    name: str
    email: str = ""

    def __post_init__(self) -> None:
        unrecordable = any(c in self.name for c in "<>\n\0") or any(c in self.email for c in ">\n\0")
        if not self.name.strip() or unrecordable:
            raise ValueError(f"git cannot record the author {self.name!r} <{self.email!r}>")


LLVIM = Author("llvim", "llvim")

SETTINGS = {
    "core.hooksPath": os.devnull,  # no hook runs, from the repo or anywhere
    "commit.gpgSign": "false",
    "gc.auto": "0",  # tidying is ours (see repack), not a side effect of some command
    "maintenance.auto": "false",
    "core.fsmonitor": "false",
}
PACKS = 50  # more packs than this, and a commit merges them in the background
LOOSE = 6700  # the same for loose objects, estimated as git gc does it: those in objects/17, times 256
SCRATCH_AGE = 3600  # seconds; a scratch ref older than this was left by a commit that died


def env() -> dict[str, str]:
    """The environment of every git llvim runs: none of the user's GIT_ variables or config files, and SETTINGS."""
    env = {name: value for name, value in os.environ.items() if not name.startswith("GIT_")}
    env |= {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0"}
    env["GIT_CONFIG_COUNT"] = str(len(SETTINGS))
    for i, (key, value) in enumerate(SETTINGS.items()):
        env[f"GIT_CONFIG_KEY_{i}"], env[f"GIT_CONFIG_VALUE_{i}"] = key, value
    return env


def is_branch_name(name: str) -> bool:
    return subprocess.run(["git", "check-ref-format", f"refs/heads/{name}"], env=env()).returncode == 0


def init(repo: Path) -> None:
    if (repo / "HEAD").exists():
        return
    command = ["git", "init", "--bare", "-q", "--object-format=sha1", "--template=", str(repo)]
    done = subprocess.run(command, capture_output=True, env=env())
    if done.returncode:
        raise GitError(f"git would not make a repo at {repo}", done.stderr.decode(errors="replace"))


def target(repo: Path, ref: str) -> Commit | None:
    """Read from the ref files, not from a git process: readers ask on every change."""
    try:
        return (repo / ref).read_text().strip()
    except FileNotFoundError:
        pass
    try:
        packed = (repo / "packed-refs").read_text().splitlines()
    except FileNotFoundError:
        return None
    return next((line.split()[0] for line in packed if line.endswith(f" {ref}")), None)


async def run(repo: Path, *args: str, input: bytes | None = None) -> bytes:
    command = ["git", "--git-dir", str(repo), *args]
    pipe = subprocess.PIPE
    process = await asyncio.create_subprocess_exec(*command, stdin=pipe, stdout=pipe, stderr=pipe, env=env())
    out, err = await process.communicate(input)
    if process.returncode:
        raise GitError(f"git {args[0]} failed", err.decode(errors="replace"))
    return out


def write_blobs(repo: Path, sources: Iterable[bytes | os.PathLike]) -> list[str]:
    """Store each content, or each file's content (a link is followed), and return their ids in order. One git for
    the batch: it reads files from disk itself, so content is staged in scratch files and large files are never
    held in memory."""
    with tempfile.TemporaryDirectory(prefix="llvim-blobs-") as scratch:
        paths = []
        for i, source in enumerate(sources):
            path = Path(scratch) / str(i)
            if isinstance(source, bytes | bytearray):
                path.write_bytes(source)
            elif "\n" in str(Path(source).absolute()):  # git reads one path per line
                path.symlink_to(Path(source).absolute())
            else:
                path = Path(source).absolute()
            paths.append(path)
        if not paths:
            return []
        command = ["git", "--git-dir", str(repo), "hash-object", "-w", "--no-filters", "--stdin-paths"]
        listing = b"".join(os.fsencode(path) + b"\n" for path in paths)
        done = subprocess.run(command, input=listing, capture_output=True, env=env())
    if done.returncode:
        raise GitError("git would not store a file", done.stderr.decode(errors="replace"))
    return done.stdout.decode().split()


def write_tree(repo: Path, entries: dict[str, tuple[str, str]]) -> str | None:
    """The tree holding `entries`, path -> (mode, object id), with the folders their paths make; None for no entries.
    ValueError if a path is bad or is both a file and a folder; GitError if an object is missing."""
    root: dict = {}
    for path, entry in entries.items():
        *folders, name = file_path(path).split("/")
        node = root
        for folder in folders:
            node = node.setdefault(folder, {})
            if not isinstance(node, dict):
                raise ValueError(f"{path!r} is under a file")
        if name in node:
            raise ValueError(f"{path!r} is a folder of other entries")
        node[name] = entry
    if not root:
        return None
    command = ["git", "--git-dir", str(repo), "mktree", "-z", "--batch"]
    pipe = subprocess.PIPE
    with subprocess.Popen(command, stdin=pipe, stdout=pipe, stderr=pipe, env=env()) as process:

        def write(node: dict) -> str:
            lines = []
            for name, child in node.items():
                mode, id = ("040000", write(child)) if isinstance(child, dict) else child
                kind = {"040000": "tree", "160000": "commit"}.get(mode, "blob")
                lines.append(os.fsencode(f"{mode} {kind} {id}\t{name}") + b"\0")
            process.stdin.write(b"".join(lines) + b"\0")
            process.stdin.flush()
            made = process.stdout.readline().strip().decode()
            if not made:
                raise GitError("git would not make a tree", process.stderr.read().decode(errors="replace"))
            return made

        try:
            return write(root)
        finally:
            process.stdin.close()


def file_path(path: str, *, root: bool = False) -> str:
    """`path` if it can name a file under files/; ValueError if not. `root`: "" is allowed, for files/ itself."""
    if root and path == "":
        return path
    if not isinstance(path, str) or set(path) & {"\n", "\0"} or {"", ".", "..", ".git"} & set(path.split("/")):
        raise ValueError(f"not a file path: {path!r}")
    return path


async def move(repo: Path, ref: str, to: Commit, start: Commit | None, *, then: str = "") -> None:
    """Point `ref` at `to` if it is still at `start` (None: if it does not exist). GitError if git would not."""
    check = f"update {ref} {to} {start}" if start else f"create {ref} {to}"
    try:
        await run(repo, "update-ref", "--stdin", input=f"{check}\n{then}".encode())
    except GitError as error:
        raise GitError(f"git would not move {ref}", error.stderr) from None


async def commit(
    repo: Path,
    ref: str,
    base: Commit | None,
    changes: dict[int, bytes | None],
    next_id: int,
    where: dict[int, str],
    bucket: int,
    author: Author,
    message: str,
    files: dict[str, FileChange] | None = None,
) -> Commit | None:
    """Commit `changes` (None: removed) on top of `base`, and move `ref` there if it is still at `base`.
    None if it is not; GitError if git would not commit or move it for another reason, such as a lock file left by a
    git that died.

    `where` is the bucket of each message in `base`; on success it is updated to the new commit. The caller keeps it, so
    a commit costs the same however long the log is.

    `files` are applied in order to files/, each path relative to it ("": files/ itself), so a change inside a path
    an earlier one set applies on top of it."""
    scratch = f"refs/llvim/scratch/{secrets.token_hex(8)}"
    script = _script(scratch, base, changes, next_id, where, bucket, author, message, files or {})
    made = (await run(repo, "fast-import", "--quiet", input=script)).decode().strip()
    try:
        await move(repo, ref, made, base, then=f"delete {scratch}\n")
    except GitError:
        with suppress(GitError):
            await run(repo, "update-ref", "-d", scratch)
        if target(repo, ref) != base:
            return None
        raise
    for id, content in changes.items():
        if content is None:
            where.pop(id, None)
        else:
            where.setdefault(id, _bucket(id, bucket))
    if untidy(repo):
        threading.Thread(target=repack, args=(repo,), daemon=True).start()
    return made


def _script(
    scratch: str,
    base: Commit | None,
    changes: dict[int, bytes | None],
    next_id: int,
    where: dict[int, str],
    bucket: int,
    author: Author,
    message: str,
    files: dict[str, FileChange],
) -> bytes:
    when, text, next_text = f"{int(time.time())} +0000", message.encode(), str(next_id).encode()
    script = [
        f"commit {scratch}".encode(),
        b"mark :1",
        f"author {author.name} <{author.email}> {when}".encode(),
        f"committer {LLVIM.name} <{LLVIM.email}> {when}".encode(),
        f"data {len(text)}".encode(),
        text,
    ]
    script += [f"from {base}".encode()] if base else []
    for id, content in changes.items():
        path = f"messages/{where.get(id, _bucket(id, bucket))}/{id}"
        if content is not None:
            script += [f"M 100644 inline {path}".encode(), f"data {len(content)}".encode(), content]
        elif id in where:
            script.append(f"D {path}".encode())
    for path, change in files.items():
        quoted = _quote(f"files/{path}" if path else "files")
        line = f"D {quoted}" if change is None else f"M {change[0]} {change[1]} {quoted}"
        script.append(os.fsencode(line))
    script += [b"M 100644 inline next", f"data {len(next_text)}".encode(), next_text]
    script += [b"get-mark :1", b""]
    return b"\n".join(script)


def _quote(path: str) -> str:
    """A path as fast-import reads it: quoted, so one starting with `"` or holding spaces means what it says."""
    return '"' + path.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _bucket(id: int, size: int) -> str:
    return str(id // size * size)


def untidy(repo: Path) -> bool:
    """Too many packs or loose objects. fast-import leaves a pack per commit, or loose objects for a small one."""
    try:
        loose = len(os.listdir(repo / "objects" / "17")) * 256
    except FileNotFoundError:
        loose = 0
    return loose > LOOSE or len(list((repo / "objects" / "pack").glob("*.pack"))) > PACKS


def repack(repo: Path) -> None:
    """Drop old scratch refs and merge the packs. One at a time; a commit that finds one running skips it."""
    with open(repo / "llvim" / "repack.lock", "wb") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        _drop_old_scratch(repo)
        command = ["git", "--git-dir", str(repo), "repack", "-d", "-q", "--geometric=2"]
        subprocess.run(command, capture_output=True, env=env())


def _drop_old_scratch(repo: Path) -> None:
    listing = ["git", "--git-dir", str(repo), "for-each-ref", "--format=%(objectname) %(committerdate:unix) %(refname)"]
    found = subprocess.run([*listing, "refs/llvim/scratch/"], capture_output=True, text=True, env=env()).stdout
    oldest = time.time() - SCRATCH_AGE
    old = [line.split() for line in found.splitlines()]
    deletes = "".join(f"delete {ref} {commit}\n" for commit, when, ref in old if int(when) < oldest)
    if deletes:
        update = ["git", "--git-dir", str(repo), "update-ref", "--stdin"]
        subprocess.run(update, input=deletes, capture_output=True, text=True, env=env())


class Objects:
    """One `git cat-file --batch` kept running, so reading an object is a pipe round trip, not a new process."""

    def __init__(self, repo: Path):
        self._repo, self._process, self._lock = repo, None, threading.Lock()

    def get(self, name: str) -> tuple[str, bytes] | None:
        """The id and content of the object `name` names, or None."""
        found = self.lookup(name)
        return (found[0], found[2]) if found else None

    def lookup(self, name: str) -> tuple[str, str, bytes] | None:
        """The id, type and content of the object `name` names, or None."""
        with self._lock:
            if self._process is None:
                command = ["git", "--git-dir", str(self._repo), "cat-file", "--batch"]
                pipe = subprocess.PIPE
                self._process = subprocess.Popen(command, stdin=pipe, stdout=pipe, stderr=subprocess.DEVNULL, env=env())
                weakref.finalize(self, _stop, self._process)
            self._process.stdin.write(os.fsencode(name) + b"\n")
            self._process.stdin.flush()
            header = self._process.stdout.readline().split()
            if len(header) != 3:
                return None
            content = self._process.stdout.read(int(header[2]) + 1)[:-1]
            return header[0].decode(), header[1].decode(), content


def _stop(process: subprocess.Popen) -> None:
    process.stdin.close()
    process.wait()
    process.stdout.close()


def _entries(tree: bytes) -> Iterator[tuple[str, str]]:
    """The names and object ids in a raw git tree."""
    for _, name, id in _modes(tree):
        yield name, id


def _modes(tree: bytes) -> Iterator[tuple[str, str, str]]:
    """The modes, names and object ids in a raw git tree."""
    at = 0
    while at < len(tree):
        space, nul = tree.index(b" ", at), tree.index(b"\0", at)
        yield tree[at:space].decode(), os.fsdecode(tree[space + 1 : nul]), tree[nul + 1 : nul + 21].hex()
        at = nul + 21


def walk(objects: Objects, tree: str, prefix: str = "") -> Iterator[tuple[str, str, str]]:
    """The path, mode and id of every entry under `tree` that is not a folder, in git's order."""
    found = objects.lookup(tree)
    assert found is not None, f"{tree} is missing from the repo"
    for mode, name, id in _modes(found[2]):
        if mode == "40000":
            yield from walk(objects, id, f"{prefix}{name}/")
        else:
            yield prefix + name, mode, id


type Bucket = tuple[str, dict[int, tuple[str, bytes]]]  # (tree id, {message id: (blob id, content)})


@dataclass
class Tree:
    """A commit's messages, read bucket by bucket: a bucket whose tree did not change since the last read is not read
    again."""

    commit: Commit
    next_id: int
    buckets: dict[str, Bucket]
    contents: dict[int, bytes]
    where: dict[int, str]  # message id: its bucket

    @classmethod
    def read(cls, objects: Objects, commit: Commit, last: "Tree | None") -> "Tree":
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
            messages = {int(id): (blob, blobs[blob] if blob in blobs else content(blob)) for id, blob in entries}
            buckets[bucket] = (tree, messages)
        contents, where = {}, {}
        for bucket, (_, messages) in buckets.items():
            for id, (_, text) in messages.items():
                contents[id], where[id] = text, bucket
        return cls(commit, int(content(root["next"])), buckets, contents, where)
