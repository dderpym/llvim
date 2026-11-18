"""std/snapshot.py: the project folder, kept in the commit of each user message: HOOK takes it, `at` reads it back, and
BOX shows what a viewer should see of it."""

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from llvim.core import Commit, Log, Writer
from llvim.std.conversation import Entry, Tag, encode, entries
from llvim.std.panels.logviewer import text
from llvim.std.panels.logviewer.box import Box, Host, Renderer, alone
from llvim.std.panels.logviewer.boxes import lines_of
from llvim.std.store import Scan, Store, Unsteady

KB, MB, GB = 1 << 10, 1 << 20, 1 << 30
BINARY_LIMIT = 1 * MB  # a binary file over this is skipped
TEXT_LIMIT = 50 * MB  # any file over this is skipped
FOLDER_LIMIT = 1 * GB  # a folder whose kept files add up to more is skipped whole
CHANGED_LIMIT = 100 * MB  # more new or changed files than this since the last snapshot: refused
FIRST_LIMIT = 2 * GB  # more files than this in the first snapshot: refused
SNIFF = 8000  # bytes read to tell binary from text: git's own test
TRIES = 3  # scans and captures while files keep changing
NAMED = 5  # files named in a refusal
FOLDER = "project"  # where the snapshot sits in a commit's files/


@dataclass(frozen=True)
class Choice:
    skipped: tuple[str, ...]  # files, and folders as "path/", left out of the snapshot
    refused: str | None = None  # why nothing is stored, or None


@dataclass(frozen=True)
class Taken:
    """The snapshot as of a commit."""

    tree: str | None  # the project tree the commit holds; None: an empty folder
    skipped: tuple[str, ...]  # what that tree left out, so what a move to it must not touch
    refused: bool  # the turn's own snapshot was refused: the folder then was not what `tree` holds


def choose(scan: Scan, is_binary: Callable[[str], bool], first: bool = False) -> Choice:
    """What to leave out of a snapshot of `scan`, or why to take none. `first`: there is no earlier snapshot to compare
    with, so the whole folder counts against FIRST_LIMIT instead of what changed against CHANGED_LIMIT."""
    skipped = set(scan.repos)
    kept = {}
    for path, size in scan.files.items():
        if size > TEXT_LIMIT or (size > BINARY_LIMIT and is_binary(path)):
            skipped.add(path)
        else:
            kept[path] = size
    folders = _too_large(kept)
    skipped |= {folder + "/" for folder in folders}
    kept = {path: size for path, size in kept.items() if not folders.intersection(_parents(path))}
    if first:
        counted, limit, what = kept, FIRST_LIMIT, "of files for a first snapshot"
    else:
        counted = {path: size for path, size in kept.items() if path in scan.changed}
        limit, what = CHANGED_LIMIT, "of new or changed files since the last snapshot"
    total = sum(counted.values())
    refused = _refusal(counted, f"{_size(total)} {what}, over {_size(limit)}") if total > limit else None
    return Choice(tuple(sorted(skipped)), refused)


def is_binary(path: Path) -> bool:
    try:
        with open(path, "rb") as file:
            return b"\0" in file.read(SNIFF)
    except OSError:
        return False  # gone or unreadable: capture says so, if it matters


async def snapshot(log: Log, writer: Writer, text: str) -> bool:
    """The input bar's hook: stage the project folder in the commit of the message, and record what was done. False,
    so the model is not cued, when the snapshot is refused; a failure is recorded and the turn goes on."""
    try:
        choice = await _take(log, writer)
    except Exception as error:
        writer.append(_refused(f"Not snapshotted: {error}"))
        return True
    if choice.refused:
        writer.append(_refused(choice.refused))
        return False
    writer.append(encode([Tag.SNAPSHOT], skipped=list(choice.skipped)))
    return True


HOOK = snapshot


async def _take(log: Log, writer: Writer) -> Choice:
    store, head = Store(log), log.tree(FOLDER)
    unsteady: tuple[str, ...] = ()
    for _ in range(TRIES):
        scan = await store.scan(log.project, head, cache=FOLDER)
        choice = choose(scan, _binary_in(scan.dir), first=head is None)
        if choice.refused:
            return choice
        try:
            tree = await store.capture(log.project, scan, leave=choice.skipped)
        except Unsteady as error:
            unsteady = error.paths
            continue
        if tree != head:
            writer.put_tree(FOLDER, tree)
        return choice
    paths = ", ".join(unsteady[:NAMED])
    return Choice(
        (), f"Not snapshotted: files kept changing while they were read: {paths}; send again once they are written"
    )


def at(log: Log, commit: Commit) -> Taken | None:
    """The snapshot as of `commit`, from the newest record at or before it; None if no message there was snapshotted."""
    records = [entry for entry in entries(log.read(at=commit)) if is_record(entry)]
    if not records:
        return None
    taken = next((record for record in reversed(records) if not _is_refused(record)), None)
    skipped = taken.extra.get("skipped", []) if taken else []
    paths = tuple(path for path in skipped if isinstance(path, str)) if isinstance(skipped, list) else ()
    return Taken(log.tree(FOLDER, at=commit), paths, _is_refused(records[-1]))


def left_alone(log: Log, a: Commit, b: Commit) -> set[str]:
    """What the snapshot at `a` or at `b` skipped: neither holds it, so a move between them must not touch it."""
    return {path for taken in (at(log, a), at(log, b)) if taken for path in taken.skipped}


def is_record(entry: Entry) -> bool:
    return entry.tags[:1] == [Tag.SNAPSHOT]


class Note(Box):
    """A snapshot record: nothing when all was kept, a grey line naming what was skipped, the reason when refused."""

    framed = False

    def __init__(self, host: Host, messages: list[Entry]):
        super().__init__(host, messages)
        record = messages[0]
        skipped = record.extra.get("skipped") or []
        if Tag.ERROR in record.tags:
            self.lines = lines_of(text.default([Tag.ERROR], record.content))
        elif skipped and isinstance(skipped, list):
            names = text.clean(", ".join(str(path) for path in skipped))
            self.lines = lines_of(f"{text.GREY}snapshot skipped: {names}{text.RESET}\n\n")


BOX = Renderer(lambda entry: alone(entry) if is_record(entry) else None, Note, "snapshot")


def _binary_in(dir: Path) -> Callable[[str], bool]:
    return lambda path: is_binary(dir / path)


def _refused(why: str) -> bytes:
    return encode([Tag.SNAPSHOT, Tag.ERROR], why, refused=True)


def _is_refused(record: Entry) -> bool:
    return record.extra.get("refused") is True


def _too_large(kept: dict[str, int]) -> set[str]:
    """The folders to skip, deepest first: skipping a deep folder may bring the ones above it under the limit, which
    keeps more of the project than skipping a shallow one would."""
    totals: dict[str, int] = defaultdict(int)
    for path, size in kept.items():
        for folder in _parents(path):
            totals[folder] += size
    chosen = set()
    for folder in sorted(totals, key=lambda folder: (-folder.count("/"), -totals[folder], folder)):
        if totals[folder] > FOLDER_LIMIT:
            chosen.add(folder)
            for parent in _parents(folder):
                totals[parent] -= totals[folder]
    return chosen


def _refusal(counted: dict[str, int], what: str) -> str:
    largest = sorted(counted, key=lambda path: (-counted[path], path))[:NAMED]
    named = ", ".join(f"{path} ({_size(counted[path])})" for path in largest)
    return f"Not snapshotted: {what}. The largest: {named}. Add them to .gitignore, or send again after removing them."


def _size(n: int) -> str:
    for unit, name in ((GB, "GB"), (MB, "MB"), (KB, "KB")):
        if n >= unit:
            return f"{n / unit:.1f} {name}".replace(".0 ", " ")
    return f"{n} bytes"


def _parents(path: str) -> list[str]:
    """`a/b/c` -> `a`, `a/b`."""
    parts = path.split("/")
    return ["/".join(parts[:i]) for i in range(1, len(parts))]
