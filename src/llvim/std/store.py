"""std/store.py: Store, which moves files between a folder on disk and git trees in a log's repo."""

import asyncio
import hashlib
import json
import os
import re
import secrets
import stat
import struct
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from llvim.core import GitError, Log

LINK, EXECUTABLE, FILE = "120000", "100755", "100644"
FILE_MODES = (FILE, EXECUTABLE, LINK)
RACY = 2_000_000_000  # ns; a file changed this recently may change again within the same mtime, so it is not cached

type Stat = tuple[int, int, int, int, int]  # st_mode, size, mtime_ns, ctime_ns, inode: what says a file is unchanged
type Seen = tuple[Stat, str, str | None]  # its stat, its mode, and its blob id (None: it moved while being read)


class Unsteady(Exception):
    """Files changed while they were being captured, so the tree would hold some of them half-written."""

    def __init__(self, paths: Iterable[str]):
        self.paths = tuple(sorted(paths))
        super().__init__(f"files changed while being captured: {', '.join(self.paths)}")


@dataclass(frozen=True)
class Scan:
    dir: Path
    files: dict[str, int]  # path -> size, every file not ignored (and not under a repo)
    changed: frozenset[str]  # those that differ from `against`, or are not in it
    repos: tuple[str, ...]  # nested git repos found, as "path/": never entered
    _seen: dict[str, Seen] = field(default_factory=dict, repr=False, compare=False)


@dataclass(frozen=True)
class Left:
    """What checkout did not write, though the tree has another copy."""

    ignored: tuple[str, ...] = ()  # ignored on disk now, so never captured as it is
    blocked: tuple[str, ...] = ()  # a folder at the path, or a file, link or repo above it

    def __bool__(self) -> bool:
        return bool(self.ignored or self.blocked)


class Store:
    """Trees of files in a log's repo, and the folders on disk they come from and go to. It knows nothing of the log's
    head: a tree goes into a commit through `Writer.put_tree`. Each call runs in a thread: it reads and writes files."""

    def __init__(self, log: Log):
        self._log, self._caches = log, log.dir / "caches"

    async def scan(self, dir: str | os.PathLike, against: str | None, cache: str, excludes: Iterable[str] = ()) -> Scan:
        """The files of `dir` and which of them differ from the tree `against` (None: all). `cache` names a stat cache:
        a file whose stat data it holds is not read again."""
        self._cache(cache)
        return await asyncio.to_thread(self._scan, _folder(dir), against, cache, tuple(excludes))

    async def capture(self, dir: str | os.PathLike, scan: Scan, leave: Iterable[str] = ()) -> str | None:
        """The tree of the scanned files of `dir` but `leave`, or None if there are none. Raises Unsteady, storing
        no tree, if any of them changed since the scan or while being read."""
        return await asyncio.to_thread(self._capture, _same_folder(dir, scan), scan, tuple(leave))

    async def add(self, tree: str | None, changes: dict[str, bytes | Path | None]) -> str | None:
        """`tree` with `changes` made in order: content, a file on disk (as capture would store it: a link as a link,
        an executable as one), or None to remove the file or folder at a path. None if nothing is left."""
        return await asyncio.to_thread(self._add, tree, changes)

    async def checkout(
        self, tree: str | None, dir: str | os.PathLike, leave: Iterable[str] = (), scan: Scan | None = None
    ) -> Left:
        """Make `dir` hold `tree` (None: no files), but `leave` and what is unsafe to overwrite, which it returns.
        It destroys what it overwrites or deletes, uncaptured changes included: guarding them is the caller's, by
        capturing first. `scan` is a scan of `dir` just taken; without one it scans `dir` itself."""
        Path(dir).mkdir(parents=True, exist_ok=True)
        if scan is not None:
            _same_folder(dir, scan)
        return await asyncio.to_thread(self._checkout, tree, _folder(dir), tuple(leave), scan)

    def _scan(self, dir: Path, against: str | None, cache: str | None, excludes: tuple[str, ...]) -> Scan:
        target = self._log.read_tree(against) if against is not None else None
        stats, repos = _walk(dir, excludes)
        known = self._load(cache)
        seen = {}
        for path, now in stats.items():
            cached = known.get(path)
            seen[path] = cached if cached and cached[0] == now else (now, *_identify(dir / path, now))
        changed = {path for path, (_, mode, id) in seen.items() if target is None or target.get(path) != (mode, id)}
        self._save(cache, seen)
        files = {path: stats[path][1] for path in stats}
        return Scan(dir, files, frozenset(changed), repos, seen)

    def _capture(self, dir: Path, scan: Scan, leave: tuple[str, ...]) -> str | None:
        wanted = sorted(path for path in scan.files if not _left(path, leave))
        if not wanted:
            return None
        seen = scan._seen

        def moved() -> set[str]:
            return {path for path in wanted if _stat(dir / path) != seen[path][0]}

        if unsteady := moved():
            raise Unsteady(unsteady)
        to_store = [path for path in wanted if path in scan.changed]
        try:
            ids = self._log.write_blobs([_source(dir / path, seen[path][1]) for path in to_store])
        except (GitError, OSError):
            if unsteady := moved():
                raise Unsteady(unsteady) from None
            raise
        unsteady = {path for path, id in zip(to_store, ids) if id != seen[path][2]} | moved()
        if unsteady:
            raise Unsteady(unsteady)
        return self._log.write_tree({path: seen[path][1:] for path in wanted})

    def _add(self, tree: str | None, changes: dict[str, bytes | Path | None]) -> str | None:
        entries = self._log.read_tree(tree) if tree is not None else {}
        sources: dict[str, tuple[str, bytes | Path]] = {}
        for path, content in changes.items():
            _check_path(path)
            for replaced in [entry for entry in entries if _covers(path, entry) or _covers(entry, path)]:
                del entries[replaced]
                sources.pop(replaced, None)
            if isinstance(content, Path):
                st = content.lstat()
                mode = _mode(st.st_mode)
                sources[path] = (mode, _source(content, mode))
            elif content is not None:
                sources[path] = (FILE, content)
            if content is not None:
                entries[path] = ("", "")
        ids = self._log.write_blobs([source for _, source in sources.values()])
        for (path, (mode, _)), id in zip(sources.items(), ids):
            entries[path] = (mode, id)
        return self._log.write_tree(entries)

    def _checkout(self, tree: str | None, dir: Path, leave: tuple[str, ...], scan: Scan | None) -> Left:
        entries = self._log.read_tree(tree) if tree is not None else {}
        target = {path: entry for path, entry in entries.items() if entry[0] in FILE_MODES}
        scan = scan or self._scan(dir, None, None, ())
        disk = _Disk(dir)
        gone = [path for path in scan.files if path not in target and not _left(path, leave)]
        for path in gone:
            if disk.above(path) is None and disk.kind(path) == "file":
                (dir / path).unlink(missing_ok=True)
        _prune(dir, gone)
        disk, ignored, blocked = _Disk(dir), [], []
        for path, (mode, id) in sorted(target.items()):
            seen = scan._seen.get(path)
            if _left(path, leave) or (seen and seen[1:] == (mode, id)):
                continue
            if disk.above(path) is not None or disk.kind(path) in ("dir", "repo"):
                blocked.append(path)
            elif disk.kind(path) != "missing" and path not in scan.files:
                ignored.append(path)
            else:
                _write(dir / path, mode, self._log.blob(id))
        return Left(tuple(ignored), tuple(blocked))

    def _cache(self, name: str) -> Path:
        if not name or "/" in name or "\0" in name or name.startswith("."):
            raise ValueError(f"bad cache name: {name!r}")
        return self._caches / f"{name}.json"

    def _load(self, name: str | None) -> dict[str, Seen]:
        try:
            entries = json.loads(self._cache(name).read_text()) if name else {}
        except (OSError, ValueError):
            return {}
        return {path: (tuple(st), mode, id) for path, (st, mode, id) in entries.items()}

    def _save(self, name: str | None, seen: dict[str, Seen]) -> None:
        """Keep what was read, but not a file changed so recently it may change again with the same stat data, and not
        one whose content is unknown. Written whole and moved in place, so a reader never sees half a cache."""
        if not name:
            return
        settled = time.time_ns() - RACY
        kept = {path: entry for path, entry in seen.items() if entry[2] and entry[0][2] < settled}
        self._caches.mkdir(parents=True, exist_ok=True)
        scratch = self._caches / f"{secrets.token_hex(8)}.scratch"
        scratch.write_text(json.dumps(kept))
        scratch.replace(self._cache(name))


class _Rules:
    """Ignore patterns as git reads them: the last pattern that matches a path decides, a deeper `.gitignore` before a
    shallower one, `excludes` before both and `.git/info/exclude` after."""

    def __init__(self, dir: Path, excludes: tuple[str, ...]):
        self._first = [("", _patterns(excludes))]
        exclude = dir / ".git" / "info" / "exclude"
        self._last = [("", _patterns(_lines(exclude)))]
        self._dir = dir

    def within(self, chain: list, folder: str) -> list:
        """The per-folder lists in force inside `folder`, given those in force in its parent."""
        patterns = _patterns(_lines(self._dir / folder / ".gitignore"))
        return [*chain, (folder, patterns)] if patterns else chain

    def ignored(self, chain: list, path: str, is_dir: bool) -> bool:
        for base, patterns in [*self._first, *reversed(chain), *self._last]:
            relative = path[len(base) + 1 :] if base else path
            for regex, negated, dir_only in reversed(patterns):
                if (is_dir or not dir_only) and regex.fullmatch(relative):
                    return not negated
        return False


def _lines(path: Path) -> list[str]:
    try:
        return path.read_text(errors="surrogateescape").splitlines()
    except (OSError, ValueError):
        return []


def _patterns(lines: Iterable[str]) -> list[tuple[re.Pattern, bool, bool]]:
    patterns = []
    for line in lines:
        while line.endswith(" ") and not line.endswith("\\ "):
            line = line[:-1]
        if not line or line.startswith("#"):
            continue
        negated = line.startswith("!")
        line = line[negated:]
        dir_only = line.endswith("/")
        line = line.rstrip("/")
        anchored = "/" in line
        line = line.removeprefix("/")
        if line:
            patterns.append((re.compile(("" if anchored else "(?:.*/)?") + _glob(line), re.DOTALL), negated, dir_only))
    return patterns


def _glob(pattern: str) -> str:
    """A gitignore pattern as a regex: `*` and `?` stop at `/`, a `**` part matches any number of folders."""
    parts = pattern.split("/")
    regex = ""
    for i, part in enumerate(parts):
        last = i == len(parts) - 1
        if part == "**":
            regex += ".*" if last else "(?:.*/)?"
        else:
            regex += _part(part) + ("" if last else "/")
    return regex


def _part(part: str) -> str:
    regex, at = "", 0
    while at < len(part):
        c = part[at]
        if c == "*":
            regex += "[^/]*"
        elif c == "?":
            regex += "[^/]"
        elif c == "\\" and at + 1 < len(part):
            at += 1
            regex += re.escape(part[at])
        elif c == "[" and (end := part.find("]", at + 2)) != -1:
            inside = part[at + 1 : end]
            negated = inside[:1] in ("!", "^")
            inside = inside[negated:].replace("\\", "\\\\")
            regex += f"[{'^' if negated else ''}{inside}]"
            at = end
        else:
            regex += re.escape(c)
        at += 1
    return regex


def _walk(dir: Path, excludes: tuple[str, ...]) -> tuple[dict[str, Stat], tuple[str, ...]]:
    """Every file not ignored, with its stat data, and every nested repo, not entered. A file the folder's own repo
    tracks is never ignored: `git add -f` put it there."""
    rules, files, repos = _Rules(dir, excludes), {}, set()

    def enter(folder: str, chain: list) -> None:
        chain = rules.within(chain, folder)
        try:
            entries = list(os.scandir(dir / folder))
        except OSError:
            return
        for entry in entries:
            if entry.name == ".git":
                continue
            path = f"{folder}/{entry.name}" if folder else entry.name
            st = entry.stat(follow_symlinks=False)
            is_dir = stat.S_ISDIR(st.st_mode)
            if rules.ignored(chain, path, is_dir):
                continue
            if is_dir and os.path.lexists(dir / path / ".git"):
                repos.add(path + "/")
            elif is_dir:
                enter(path, chain)
            elif stat.S_ISREG(st.st_mode) or stat.S_ISLNK(st.st_mode):
                files[path] = _key(st)

    enter("", [])
    disk = _Disk(dir)
    for path in _tracked(dir) - files.keys():
        if disk.above(path) is None and disk.kind(path) == "file" and (st := _stat(dir / path)):
            files[path] = st
    return files, tuple(sorted(repos))


def _tracked(dir: Path) -> set[str]:
    """The files the git repo `dir` is in tracks, read from its index file, under `dir` and relative to it. Read
    rather than asked: only core runs git. An index it cannot read tracks nothing."""
    top = next((folder for folder in (dir, *dir.parents) if os.path.lexists(folder / ".git")), None)
    if top is None:
        return set()
    gitdir = top / ".git"
    try:
        if gitdir.is_file():
            gitdir = top / gitdir.read_text().removeprefix("gitdir:").strip()
        paths = _index_paths((gitdir / "index").read_bytes(), 32 if _sha256(gitdir) else 20)
    except (OSError, ValueError, IndexError, struct.error):
        return set()
    prefix = "" if top == dir else dir.relative_to(top).as_posix() + "/"
    return {path[len(prefix) :] for path in paths if path.startswith(prefix)}


def _sha256(gitdir: Path) -> bool:
    common = gitdir / "commondir"
    config = (gitdir / common.read_text().strip() if common.is_file() else gitdir) / "config"
    return bool(re.search(r"objectformat\s*=\s*sha256", "\n".join(_lines(config)), re.IGNORECASE))


def _index_paths(data: bytes, hash_size: int) -> list[str]:
    """The paths of a git index file, versions 2 to 4 (`gitformat-index`)."""
    if data[:4] != b"DIRC":
        raise ValueError("not a git index")
    version, count = struct.unpack(">II", data[4:12])
    at, previous, paths = 12, b"", []
    for _ in range(count):
        start = at
        mode = int.from_bytes(data[at + 24 : at + 28])
        flags = int.from_bytes(data[at + 40 + hash_size : at + 42 + hash_size])
        at += 42 + hash_size + (2 if version >= 3 and flags & 0x4000 else 0)
        if version == 4:
            strip, at = _varint(data, at)
            end = data.index(b"\0", at)
            path = previous[: len(previous) - strip] + data[at:end]
            at = end + 1
        else:
            end = data.index(b"\0", at)
            path = data[at:end]
            at = start + ((end - start + 8) & ~7)
        previous = path
        if not stat.S_ISDIR(mode):  # a sparse index holds whole folders as entries
            paths.append(os.fsdecode(path))
    return paths


def _varint(data: bytes, at: int) -> tuple[int, int]:
    c = data[at]
    value = c & 127
    while c & 128:
        at += 1
        c = data[at]
        value = ((value + 1) << 7) | (c & 127)
    return value, at + 1


class _Disk:
    """What stands at paths under one folder, each folder looked at once."""

    def __init__(self, root: Path):
        self._root, self._folders = root, {}

    def kind(self, path: str) -> str:
        """What stands at `path`: "file" (or a link), "dir", "repo" (a folder holding .git), "missing", "other"."""
        try:
            mode = (self._root / path).lstat().st_mode
        except (FileNotFoundError, NotADirectoryError):
            return "missing"
        if stat.S_ISDIR(mode):
            return "repo" if os.path.lexists(self._root / path / ".git") else "dir"
        return "file" if stat.S_ISREG(mode) or stat.S_ISLNK(mode) else "other"

    def above(self, path: str) -> tuple[str, str] | None:
        """The first folder on the way to `path` that is not a plain folder or missing, and what it is."""
        for parent in _parents(path):
            if parent not in self._folders:
                self._folders[parent] = self.kind(parent)
            if self._folders[parent] not in ("dir", "missing"):
                return parent, self._folders[parent]
        return None


def _identify(path: Path, st: Stat) -> tuple[str, str | None]:
    """The mode and blob id git would give the file, computed here so that finding what changed stores nothing. None
    if it changed while being read."""
    mode = _mode(st[0])
    try:
        if mode == LINK:
            return mode, _blob_id(os.fsencode(os.readlink(path)))
        digest = hashlib.sha1(b"blob %d\0" % st[1])
        read = 0
        with open(path, "rb") as file:
            while chunk := file.read(1 << 20):
                digest.update(chunk)
                read += len(chunk)
    except OSError:
        return mode, None
    return mode, digest.hexdigest() if read == st[1] and _stat(path) == st else None


def _blob_id(content: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(content) + content).hexdigest()


def _source(path: Path, mode: str) -> bytes | Path:
    """What to store for a file: a link's target, not what it points to."""
    return os.fsencode(os.readlink(path)) if mode == LINK else path


def _write(path: Path, mode: str, content: bytes) -> None:
    """Write a file whole: to a scratch name beside it, then moved over it, so nothing sees it half-written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    scratch = path.with_name(f".{path.name}.{secrets.token_hex(4)}.llvim")
    if mode == LINK:
        os.symlink(os.fsdecode(content), scratch)
    else:
        fd = os.open(scratch, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o777 if mode == EXECUTABLE else 0o666)
        with open(fd, "wb") as file:
            file.write(content)
    os.replace(scratch, path)


def _mode(st_mode: int) -> str:
    if stat.S_ISLNK(st_mode):
        return LINK
    return EXECUTABLE if st_mode & stat.S_IXUSR else FILE


def _key(st: os.stat_result) -> Stat:
    return (st.st_mode, st.st_size, st.st_mtime_ns, st.st_ctime_ns, st.st_ino)


def _stat(path: Path) -> Stat | None:
    try:
        return _key(path.lstat())
    except (FileNotFoundError, NotADirectoryError):
        return None


def _parents(path: str) -> list[str]:
    """`a/b/c` -> `a`, `a/b`."""
    parts = path.split("/")
    return ["/".join(parts[:i]) for i in range(1, len(parts))]


def _covers(folder: str, path: str) -> bool:
    return path == folder or path.startswith(folder + "/")


def _left(path: str, leave: tuple[str, ...]) -> bool:
    return any(path == left or (left.endswith("/") and path.startswith(left)) for left in leave)


def _prune(dir: Path, deleted: list[str]) -> None:
    """Remove the folders that deleting left empty, deepest first, or they would stay behind."""
    folders = {parent for path in deleted for parent in _parents(path)}
    for folder in sorted(folders, key=lambda folder: folder.count("/"), reverse=True):
        try:
            (dir / folder).rmdir()
        except OSError:
            pass


def _check_path(path: str) -> None:
    if not isinstance(path, str) or set(path) & {"\n", "\0"} or {"", ".", "..", ".git"} & set(path.split("/")):
        raise ValueError(f"not a file path: {path!r}")


def _folder(dir: str | os.PathLike) -> Path:
    dir = Path(dir).resolve()
    if not dir.is_dir():
        raise NotADirectoryError(f"not a folder: {dir}")
    return dir


def _same_folder(dir: str | os.PathLike, scan: Scan) -> Path:
    dir = _folder(dir)
    if dir != scan.dir:
        raise ValueError(f"the scan is of {scan.dir}, not {dir}")
    return dir
