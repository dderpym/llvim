"""std/snapshot.py: the project folder kept in the commit of each user message, the size rules, and reading it back. The
store and the log are stubs."""

import pytest

from llvim.core import Request
from llvim.std import snapshot
from llvim.std.conversation import entries
from llvim.std.panels.logviewer.box import group, make
from llvim.std.snapshot import GB, MB, Choice, Taken, at, choose, is_binary, left_alone
from llvim.std.store import Scan, Unsteady


def scan_of(files, changed=None, repos=(), dir="/p"):
    return Scan(dir, dict(files), frozenset(files if changed is None else changed), tuple(repos))


def never_binary(path):
    return False


def filled(folder, size, piece=40 * MB):
    """Files in `folder` adding up to `size`, none of them large enough to be skipped alone."""
    sizes = [piece] * (size // piece) + ([size % piece] if size % piece else [])
    return {f"{folder}/{i}": each for i, each in enumerate(sizes)}


# --- the size rules ---


def test_a_large_binary_file_is_skipped_a_text_one_of_its_size_is_kept_and_a_huge_one_is_skipped_whatever_it_holds():
    files = {"small.bin": MB, "big.bin": 2 * MB, "big.txt": 2 * MB, "huge.txt": 51 * MB}
    choice = choose(scan_of(files), lambda path: path.endswith(".bin"), first=True)
    assert choice == Choice(("big.bin", "huge.txt"))


def test_only_a_file_over_a_megabyte_is_read_to_tell_whether_it_is_binary():
    looked = []
    choose(scan_of({"a": MB, "b": MB + 1, "c": 60 * MB}), lambda path: looked.append(path) or False, first=True)
    assert looked == ["b"]


def test_every_nested_repo_is_skipped_as_a_folder():
    assert choose(scan_of({"a": 1}, repos=["vendor/lib/"]), never_binary).skipped == ("vendor/lib/",)


def test_the_deepest_folder_over_a_gigabyte_is_skipped_and_the_folders_above_it_are_kept_if_that_brings_them_under():
    cases = {
        "deep one alone": (filled("a/b", GB + 1) | filled("a", GB // 2), ("a/b/",)),
        "two siblings, each under": (filled("a/b", GB // 2 + 1) | filled("a/c", GB // 2 + 1), ("a/",)),
        "the parent still over": (
            filled("a/b", GB + 1) | filled("a/c", GB // 2) | filled("a", GB // 2 + 1),
            ("a/", "a/b/"),
        ),
        "nothing over": (filled("a", GB) | filled("b", GB), ()),
    }
    for case, (files, skipped) in cases.items():
        assert choose(scan_of(files), never_binary, first=False).skipped == skipped, case


def test_skipped_files_do_not_count_towards_a_folder():
    files = filled("a", GB - 10 * MB) | {"a/y.bin": 20 * MB}
    assert choose(scan_of(files), lambda path: path.endswith(".bin")).skipped == ("a/y.bin",)


def test_more_than_100_mb_of_new_or_changed_files_is_refused_naming_the_five_largest():
    files = {f"f{i}": (10 + i) * MB for i in range(8)} | {"old": 45 * MB, "skip.bin": 40 * MB}
    choice = choose(scan_of(files, changed=set(files) - {"old"}), lambda path: path.endswith(".bin"))
    assert choice.refused is not None and choice.skipped == ("skip.bin",)
    assert "f7 (17 MB), f6 (16 MB), f5 (15 MB), f4 (14 MB), f3 (13 MB)." in choice.refused
    assert "f2" not in choice.refused and "old" not in choice.refused and "skip.bin" not in choice.refused
    assert ".gitignore" in choice.refused and "send again after removing them" in choice.refused


def test_what_did_not_change_or_is_skipped_does_not_count_towards_the_limit():
    files = {"old": 45 * MB, "new": 45 * MB, "newer": 45 * MB, "skip.bin": 40 * MB}
    assert (
        choose(scan_of(files, changed={"new", "newer", "skip.bin"}), lambda path: path.endswith(".bin")).refused is None
    )


def test_a_first_snapshot_may_hold_up_to_2_gb_and_is_refused_over_it():
    under = filled("d0", 900 * MB) | filled("d1", 900 * MB) | {"top": 45 * MB}
    over = under | filled("d2", 900 * MB)
    assert choose(scan_of(under), never_binary, first=True).refused is None
    assert choose(scan_of(under), never_binary, first=False).refused is not None
    refused = choose(scan_of(over), never_binary, first=True).refused
    assert refused is not None and "first snapshot" in refused and "top (45 MB)" in refused


def test_a_file_with_a_nul_in_its_first_8000_bytes_is_binary_and_one_with_a_nul_after_them_is_not(tmp_path):
    cases = {"early": b"text\0more", "late": b"x" * 8000 + b"\0", "text": b"plain", "missing": None}
    for name, content in cases.items():
        if content is not None:
            (tmp_path / name).write_bytes(content)
        assert is_binary(tmp_path / name) == (name == "early"), name


# --- the hook ---


class StubStore:
    """Scans and captures that a test lines up: each call takes the next one; an exception is raised."""

    def __init__(self, scans, captures):
        self.scans, self.captures, self.calls = list(scans), list(captures), []

    async def scan(self, dir, against, cache, excludes=()):
        self.calls.append(("scan", dir, against, cache))
        found = self.scans.pop(0) if len(self.scans) > 1 else self.scans[0]
        if isinstance(found, Exception):
            raise found
        return found

    async def capture(self, dir, scan, leave=()):
        self.calls.append(("capture", dir, scan, tuple(leave)))
        found = self.captures.pop(0)
        if isinstance(found, Exception):
            raise found
        return found


@pytest.fixture
def store(monkeypatch, fake_log, tmp_path):
    """`store(scans, captures)`: the StubStore the hook will use. The project is an empty folder."""
    fake_log.project = tmp_path

    def make_store(scans, captures=()):
        stub = StubStore(scans, captures)
        monkeypatch.setattr(snapshot, "Store", lambda log: stub)
        return stub

    return make_store


def tree_of(log, **files):
    ids = log.write_blobs([content.encode() for content in files.values()])
    return log.write_tree({path: ("100644", id) for path, id in zip(files, ids)})


async def send(log, text="hi"):
    """What the bar does around a hook: claim, write the message, run it, commit. Returns what it returned."""
    async with await log.claim(Request(0)) as writer:
        writer.append(b"the user message")
        went_on = await snapshot.HOOK(log, writer, text)
        await writer.commit()
    return went_on


def records(log):
    return [(e.tags, e.content, e.extra) for e in entries(log.read()) if snapshot.is_record(e)]


async def test_the_folder_is_staged_with_the_message_and_recorded_with_what_it_skipped(fake_log, store):
    tree = tree_of(fake_log, a="1")
    stub = store([scan_of({"a": 1, "z.bin": 60 * MB}, repos=["lib/"], dir=fake_log.project)], [tree])
    assert await send(fake_log) is True
    assert fake_log.tree("project") == tree
    assert records(fake_log) == [(["snapshot"], "", {"skipped": ["lib/", "z.bin"]})]
    assert stub.calls[0] == ("scan", fake_log.project, None, "project")
    assert stub.calls[1][2:] == (stub.scans[0], ("lib/", "z.bin"))


async def test_the_scan_is_against_the_snapshot_the_head_holds_and_an_unchanged_tree_is_not_put_again(fake_log, store):
    tree = tree_of(fake_log, a="1")
    store([scan_of({"a": 1}, dir=fake_log.project)], [tree, tree])
    await send(fake_log)
    async with await fake_log.claim(Request(0)) as writer:
        put = []
        writer.put_tree = lambda path, tree: put.append((path, tree))
        stub = store([scan_of({"a": 1}, changed=(), dir=fake_log.project)], [tree])
        assert await snapshot.HOOK(fake_log, writer, "again") is True
    assert stub.calls[0][2] == tree and put == []


async def test_a_folder_emptied_since_the_last_snapshot_is_a_snapshot_of_nothing(fake_log, store):
    store([scan_of({"a": 1}, dir=fake_log.project)], [tree_of(fake_log, a="1")])
    await send(fake_log)
    store([scan_of({}, dir=fake_log.project)], [None])
    assert await send(fake_log) is True
    assert fake_log.tree("project") is None and len(records(fake_log)) == 2


async def test_a_refused_snapshot_stores_nothing_ends_the_turn_and_is_the_only_message_saying_why(fake_log, store):
    stub = store(
        [
            scan_of(
                {"big": 45 * MB} | filled("d0", 900 * MB) | filled("d1", 900 * MB) | filled("d2", 900 * MB),
                dir=fake_log.project,
            )
        ]
    )
    assert await send(fake_log) is False
    assert fake_log.tree("project") is None and [call[0] for call in stub.calls] == ["scan"]
    [(tags, why, extra)] = records(fake_log)
    assert tags == ["snapshot", "error"] and extra == {"refused": True} and "big (45 MB)" in why
    assert [e.tags for e in entries(fake_log.read())] == [[], ["snapshot", "error"]]


async def test_files_that_change_while_read_are_scanned_and_captured_again(fake_log, store):
    tree = tree_of(fake_log, a="2")
    stub = store([scan_of({"a": 1}, dir=fake_log.project)], [Unsteady(["a"]), tree])
    assert await send(fake_log) is True
    assert fake_log.tree("project") == tree and [call[0] for call in stub.calls] == ["scan", "capture"] * 2


async def test_files_still_changing_after_three_tries_are_refused_naming_up_to_five_of_them(fake_log, store):
    paths = [f"log{i}" for i in range(7)]
    stub = store([scan_of(dict.fromkeys(paths, 1), dir=fake_log.project)], [Unsteady(paths)] * 3)
    assert await send(fake_log) is False
    [(tags, why, _)] = records(fake_log)
    assert len(stub.calls) == 6 and tags == ["snapshot", "error"]
    assert "files kept changing while they were read: log0, log1, log2, log3, log4;" in why and "log5" not in why
    assert "send again once they are written" in why


async def test_any_other_failure_is_recorded_and_the_turn_goes_on(fake_log, store):
    store([OSError("disk on fire")])
    assert await send(fake_log) is True
    assert records(fake_log) == [(["snapshot", "error"], "Not snapshotted: disk on fire", {"refused": True})]
    assert fake_log.tree("project") is None


# --- reading it back ---


async def take(log, store, tree, scan):
    store([scan], [tree])
    await send(log)
    return log.head()


async def test_a_commit_holds_the_tree_and_skips_of_the_newest_snapshot_at_or_before_it(fake_log, store):
    fake_log.say(["user"], "before any snapshot")
    assert at(fake_log, fake_log.head()) is None
    one = tree_of(fake_log, a="1")
    first = await take(fake_log, store, one, scan_of({"a": 1, "b.bin": 60 * MB}, dir=fake_log.project))
    fake_log.say(["assistant"], "answer")
    assert at(fake_log, fake_log.head()) == at(fake_log, first) == Taken(one, ("b.bin",), False)


async def test_a_refused_turn_has_the_previous_tree_and_skips_flagged_refused(fake_log, store):
    one = tree_of(fake_log, a="1")
    await take(fake_log, store, one, scan_of({"a": 1, "lib/x": 1}, repos=["vendor/"], dir=fake_log.project))
    store([scan_of({"a": 1} | filled("new", 200 * MB), dir=fake_log.project)])
    await send(fake_log)
    assert at(fake_log, fake_log.head()) == Taken(one, ("vendor/",), True)


async def test_what_either_snapshot_skipped_is_left_alone_by_a_move_between_them(fake_log, store):
    fake_log.say(["user"], "nothing yet")
    none = fake_log.head()
    a = await take(fake_log, store, tree_of(fake_log, a="1"), scan_of({"a": 1}, repos=["r/"], dir=fake_log.project))
    b = await take(fake_log, store, tree_of(fake_log, a="2"), scan_of({"a": 1, "z": 60 * MB}, dir=fake_log.project))
    assert left_alone(fake_log, a, b) == {"r/", "z"}
    assert left_alone(fake_log, none, a) == {"r/"}


# --- in the viewer ---


def test_the_viewer_shows_nothing_for_a_full_snapshot_a_grey_line_for_skips_and_the_reason_for_a_refusal(
    entry, stub_host
):
    full = entry(["snapshot"], skipped=[])
    partial = entry(["snapshot"], skipped=["a.bin", "data/"])
    refused = entry(["snapshot", "error"], "Not snapshotted: too big", refused=True)
    other = entry(["user"], "hi")
    groups = group([full, partial, refused, other], [snapshot.BOX])
    boxes = {claimed[0].id: make(renderer, stub_host, claimed) for renderer, claimed in groups.values()}
    assert other.id not in boxes
    assert boxes[full.id].lines == []
    assert boxes[partial.id].lines[0] == "\x1b[38;5;245msnapshot skipped: a.bin, data/\x1b[0m"
    assert "Not snapshotted: too big" in boxes[refused.id].lines and "error" in boxes[refused.id].lines[0]
