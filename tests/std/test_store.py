"""std/store.py: Store, which moves files between a folder on disk and git trees in a log's repo."""

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from llvim.std import store as store_module
from llvim.std.store import Left, Store, Unsteady


@pytest.fixture
def store(fake_log):
    return Store(fake_log)


@pytest.fixture
def dir(tmp_path):
    dir = tmp_path / "work"
    dir.mkdir()
    return dir


def write(dir: Path, files: dict[str, str]) -> None:
    for path, content in files.items():
        (dir / path).parent.mkdir(parents=True, exist_ok=True)
        (dir / path).write_text(content)


def on_disk(dir: Path) -> dict[str, str]:
    found = {}
    for root, folders, names in os.walk(dir):
        folders[:] = [folder for folder in folders if folder != ".git"]
        for name in names:
            path = Path(root) / name
            found[path.relative_to(dir).as_posix()] = os.readlink(path) if path.is_symlink() else path.read_text()
    return found


def git_in(dir: Path, *args: str) -> None:
    """Git as the user runs it in their own repo, with none of their settings: only to set up a folder."""
    env = {name: value for name, value in os.environ.items() if not name.startswith("GIT_")}
    env |= {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
    subprocess.run(["git", "-C", str(dir), *args], check=True, capture_output=True, env=env)


def settle(dir: Path) -> None:
    """Make the files written just now look written an hour ago, so a cache keeps them: one changed just now may change
    again unseen. Others are left alone, as touching a file changes its stat data."""
    an_hour_ago = time.time() - 3600
    for path in dir.rglob("*"):
        if path.is_file() and not path.is_symlink() and path.stat().st_mtime > an_hour_ago + 60:
            os.utime(path, (an_hour_ago, an_hour_ago))


async def snapshot(store, dir: Path, cache: str = "main", against: str | None = None) -> str | None:
    return await store.capture(dir, await store.scan(dir, against, cache))


async def test_a_scan_lists_every_file_with_its_size(store, dir):
    write(dir, {"a": "1", "sub/deep/b": "22"})
    (dir / "link").symlink_to("sub")
    scan = await store.scan(dir, None, "main")
    assert scan.dir == dir.resolve()
    assert scan.files == {"a": 1, "sub/deep/b": 2, "link": 3}
    assert scan.changed == {"a", "sub/deep/b", "link"}
    assert scan.repos == ()


async def test_a_scan_leaves_out_what_is_ignored(store, dir):
    write(dir, {".gitignore": "*.log\n", "sub/.gitignore": "tmp/\n", "a.log": "", "sub/tmp/x": "", "sub/keep": ""})
    write(dir, {"secret": "", "build/out": "", "kept": ""})
    git_in(dir, "init", "-q")
    (dir / ".git" / "info").mkdir(exist_ok=True)
    (dir / ".git" / "info" / "exclude").write_text("secret\n")
    scan = await store.scan(dir, None, "main", excludes=["build/"])
    assert set(scan.files) == {".gitignore", "sub/.gitignore", "sub/keep", "kept"}


async def test_a_file_the_folders_own_repo_tracks_is_never_ignored(store, dir):
    write(dir, {".gitignore": "*.log\n", "forced.log": "", "other.log": ""})
    git_in(dir, "init", "-q")
    git_in(dir, "add", "-f", "forced.log")
    for against in (None, await snapshot(store, dir)):
        scan = await store.scan(dir, against, "main", excludes=["forced.log"])
        assert set(scan.files) == {".gitignore", "forced.log"}, against


async def test_a_file_ignored_after_it_was_captured_is_no_longer_scanned(store, dir):
    write(dir, {"a": "", "b": ""})
    tree = await snapshot(store, dir)
    write(dir, {".gitignore": "b\n"})
    assert set((await store.scan(dir, tree, "main")).files) == {"a", ".gitignore"}


async def test_a_nested_repo_is_reported_and_never_entered(store, dir):
    write(dir, {"a": "", "inner/x": "", "inner/deep/y": ""})
    git_in(dir / "inner", "init", "-q")
    scan = await store.scan(dir, None, "main")
    assert (set(scan.files), scan.repos) == ({"a"}, ("inner/",))


async def test_a_captured_folder_that_became_a_repo_is_reported_and_its_files_left_out(store, dir):
    write(dir, {"lib/x": ""})
    tree = await snapshot(store, dir)
    git_in(dir / "lib", "init", "-q")
    scan = await store.scan(dir, tree, "main")
    assert (scan.files, scan.repos) == ({}, ("lib/",))


async def test_a_captured_file_that_became_a_folder_holds_new_files_or_is_a_repo(store, dir):
    write(dir, {"plain": "", "repo": ""})
    tree = await snapshot(store, dir)
    for path in ("plain", "repo"):
        (dir / path).unlink()
    write(dir, {"plain/x": "", "repo/y": ""})
    git_in(dir / "repo", "init", "-q")
    scan = await store.scan(dir, tree, "main")
    assert (scan.files, scan.changed, scan.repos) == ({"plain/x": 0}, {"plain/x"}, ("repo/",))


async def test_changed_is_what_differs_from_against(store, dir):
    write(dir, {"same": "s", "edited": "e", "gone": "g"})
    tree = await snapshot(store, dir)
    write(dir, {"edited": "E", "new": "n"})
    (dir / "gone").unlink()
    scan = await store.scan(dir, tree, "main")
    assert set(scan.files) == {"same", "edited", "new"}
    assert scan.changed == {"edited", "new"}


async def test_a_scan_with_a_cache_agrees_with_one_without(store, dir):
    write(dir, {"a": "1", "b/c": "2"})
    first = await snapshot(store, dir, "kept")
    second = await store.add(first, {"a": b"changed", "d": b"new"})
    steps = [
        ("unchanged", first, lambda: None),
        ("a file edited", first, lambda: write(dir, {"a": "3"})),
        ("against a tree the cache was not built for", second, lambda: None),
        ("a file grown", second, lambda: write(dir, {"b/c": "2222"})),
        ("a file removed", first, lambda: (dir / "a").unlink()),
        ("against nothing", None, lambda: write(dir, {"e": ""})),
    ]
    for count, (step, against, change) in enumerate(steps):
        change()
        settle(dir)
        cached = await store.scan(dir, against, "kept")
        fresh = await store.scan(dir, against, f"fresh{count}")
        assert (cached.files, cached.changed) == (fresh.files, fresh.changed), step


async def test_an_unknown_tree_or_a_bad_cache_name_is_refused(store, dir):
    for against, cache in [("1" * 40, "main"), (None, "a/b"), (None, ""), (None, ".hidden")]:
        with pytest.raises(ValueError):
            await store.scan(dir, against, cache)
            pytest.fail(f"accepted {against!r}, {cache!r}")


async def test_capture_and_checkout_bring_back_files_exactly(store, dir, tmp_path):
    write(dir, {"text": "a\r\nb\n", ".gitattributes": "* text eol=crlf\n", "sub/x": "x"})
    (dir / "run").write_text("#!/bin/sh\n")
    (dir / "run").chmod(0o755)
    (dir / "link").symlink_to("sub/x")
    tree = await snapshot(store, dir)
    other = tmp_path / "other"
    assert await store.checkout(tree, other) == Left()
    assert on_disk(other) == on_disk(dir)
    assert os.access(other / "run", os.X_OK)
    assert (other / "link").is_symlink()


async def test_capture_leaves_out_what_it_is_told_to(store, dir):
    write(dir, {"a": "", "b": "", "skip": "", "out/x": "", "outer": ""})
    tree = await store.capture(dir, await store.scan(dir, None, "main"), leave=["skip", "out/"])
    assert sorted(await files_of(store, tree)) == ["a", "b", "outer"]


async def test_capturing_no_files_gives_none(store, dir):
    write(dir, {".gitignore": "*\n"})
    assert await snapshot(store, dir) is None


async def test_a_file_that_changed_since_the_scan_is_not_captured(store, dir):
    write(dir, {"steady": "s", "grown": "g", "gone": "x"})
    tree = await snapshot(store, dir)
    write(dir, {"grown": "g1", "gone": "x1"})
    scan = await store.scan(dir, tree, "main")
    write(dir, {"grown": "g12"})
    (dir / "gone").unlink()
    with pytest.raises(Unsteady) as raised:
        await store.capture(dir, scan)
    assert raised.value.paths == ("gone", "grown")
    assert (await store.scan(dir, tree, "main")).changed == {"grown"}


async def test_a_scan_against_a_captured_tree_finds_only_what_changed_since(store, dir):
    write(dir, {"a": "1"})
    first = await snapshot(store, dir)
    write(dir, {"a": "2"})
    second = await snapshot(store, dir, against=first)
    write(dir, {"b": ""})
    scan = await store.scan(dir, second, "main")
    assert scan.changed == {"b"}


async def test_a_scan_of_another_folder_is_refused(store, dir, tmp_path):
    scan = await store.scan(dir, None, "main")
    with pytest.raises(ValueError):
        await store.capture(tmp_path, scan)
    with pytest.raises(ValueError):
        await store.checkout(None, tmp_path, scan=scan)


async def files_of(store, tree: str | None) -> list[str]:
    return [path for path, _ in await contents(store, tree)]


async def contents(store, tree: str | None) -> list[tuple[str, bytes]]:
    log = store._log
    return sorted((path, log.blob(id)) for path, (_, id) in (log.read_tree(tree) if tree else {}).items())


async def test_add_writes_content_and_files_and_removes_files_and_folders(store, dir):
    write(dir, {"keep": "k", "drop": "d", "folder/a": "a", "folder/b": "b", "source": "from disk"})
    tree = await snapshot(store, dir)
    made = await store.add(tree, {"drop": None, "folder": None, "new/x": b"x", "copied": dir / "source"})
    assert await contents(store, made) == [
        ("copied", b"from disk"),
        ("keep", b"k"),
        ("new/x", b"x"),
        ("source", b"from disk"),
    ]


async def test_add_stores_a_file_on_disk_as_capture_does(store, dir):
    write(dir, {"plain": "p", "run": "#!/bin/sh\n"})
    (dir / "run").chmod(0o755)
    (dir / "link").symlink_to("plain")
    captured = await snapshot(store, dir)
    added = await store.add(None, {name: dir / name for name in ("plain", "run", "link")})
    assert added == captured


async def test_add_puts_a_file_where_a_folder_was_and_a_folder_where_a_file_was(store):
    tree = await store.add(None, {"a/b": b"", "c": b""})
    assert await files_of(store, await store.add(tree, {"a": b"", "c/d": b""})) == ["a", "c/d"]


async def test_add_applies_changes_in_order(store):
    tree = await store.add(None, {"a/b": b"1", "a": None, "a/c": b"2"})
    assert await files_of(store, tree) == ["a/c"]


async def test_a_tree_with_nothing_left_is_none(store):
    assert await store.add(None, {}) is None
    assert await store.add(await store.add(None, {"a": b""}), {"a": None}) is None


async def test_add_refuses_a_path_that_cannot_name_a_file(store):
    for path in ["", "/a", "a/", "a//b", "../a", "a/./b", ".git/x", "a\nb"]:
        with pytest.raises(ValueError):
            await store.add(None, {path: b""})
            pytest.fail(f"accepted {path!r}")


async def test_checkout_makes_the_folder_hold_the_tree(store, dir):
    write(dir, {"a": "1", "b/c": "2"})
    tree = await snapshot(store, dir)
    write(dir, {"a": "changed", "extra/deep/x": "", "b/new": ""})
    (dir / "b" / "c").unlink()
    assert await store.checkout(tree, dir) == Left()
    assert on_disk(dir) == {"a": "1", "b/c": "2"}
    assert not (dir / "extra").exists()


async def test_checkout_of_no_tree_deletes_every_file_it_scanned(store, dir):
    write(dir, {".gitignore": "*.log\n", "a": "", "b/c": "", "x.log": ""})
    await store.checkout(None, dir)
    assert on_disk(dir) == {"x.log": ""}


async def test_checkout_does_not_write_a_file_that_is_already_right(store, dir):
    write(dir, {"same": "s", "other": "o"})
    tree = await snapshot(store, dir)
    write(dir, {"other": "O"})
    os.utime(dir / "same", (1, 1))
    await store.checkout(tree, dir)
    assert (dir / "same").stat().st_mtime == 1
    assert (dir / "other").read_text() == "o"


async def test_checkout_does_not_touch_what_it_is_told_to_leave(store, dir):
    write(dir, {"a": "1", "f/x": "1"})
    tree = await snapshot(store, dir)
    write(dir, {"a": "2", "f/x": "2", "f/y": "new", "g": "new"})
    await store.checkout(tree, dir, leave=["a", "f/"])
    assert on_disk(dir) == {"a": "2", "f/x": "2", "f/y": "new"}


async def test_checkout_does_not_write_through_or_over_what_it_would_destroy(store, dir, tmp_path):
    write(dir, {"folder": "", "under_file/x": "", "under_link/x": "", "under_repo/x": ""})
    tree = await snapshot(store, dir)
    for case in ["folder", "under_file", "under_link", "under_repo"]:
        shutil.rmtree(dir / case) if (dir / case).is_dir() else (dir / case).unlink()
    ignored = "*.keep\nunder_file\nunder_link\n"
    write(dir, {".gitignore": ignored, "folder/inside.keep": "", "under_file": "", "under_repo/y": ""})
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (dir / "under_link").symlink_to(elsewhere)
    git_in(dir / "under_repo", "init", "-q")
    left = await store.checkout(tree, dir)
    assert left.blocked == ("folder", "under_file/x", "under_link/x", "under_repo/x")
    assert left.ignored == ()
    assert (dir / "folder" / "inside.keep").exists()
    assert (dir / "under_file").is_file()
    assert list(elsewhere.iterdir()) == []
    assert (dir / "under_repo" / ".git").is_dir()


async def test_checkout_does_not_overwrite_a_file_that_is_ignored_now(store, dir):
    write(dir, {"settings.local": "captured"})
    tree = await snapshot(store, dir)
    write(dir, {".gitignore": "*.local\n", "settings.local": "uncaptured"})
    left = await store.checkout(tree, dir)
    assert left == Left(ignored=("settings.local",))
    assert bool(left)
    assert (dir / "settings.local").read_text() == "uncaptured"


async def test_checkout_leaves_ignored_files_and_the_folders_holding_them(store, dir):
    write(dir, {".gitignore": "*.o\n", "build/a.o": "", "build/a.c": "", "src/b.c": ""})
    await store.checkout(await store.add(None, {".gitignore": b"*.o\n"}), dir)
    assert on_disk(dir) == {".gitignore": "*.o\n", "build/a.o": ""}


async def test_after_a_checkout_a_scan_against_its_tree_finds_only_what_changed_since(store, dir):
    write(dir, {"a": "1"})
    first = await snapshot(store, dir)
    write(dir, {"a": "2"})
    second = await snapshot(store, dir, against=first)
    await store.checkout(first, dir, scan=await store.scan(dir, second, "main"))
    write(dir, {"b": ""})
    for cache in ("main", "fresh"):
        assert (await store.scan(dir, first, cache)).changed == {"b"}, cache


async def test_a_file_the_cache_holds_is_not_read_again(store, dir, monkeypatch):
    write(dir, {"a": "content", "b": "content"})
    settle(dir)
    tree = await snapshot(store, dir)
    write(dir, {"b": "changed"})
    settle(dir)
    opened = []
    monkeypatch.setattr(
        store_module, "open", lambda path, *rest: opened.append(path) or open(path, *rest), raising=False
    )
    assert (await store.scan(dir, tree, "main")).changed == {"b"}
    assert opened == [dir / "b"]
    await store.scan(dir, tree, "fresh")
    assert sorted(opened[1:]) == [dir / "a", dir / "b"], "without a cache it reads every file"


async def test_ignore_patterns_mean_what_they_mean_to_git(store, dir):
    files = [
        "a.log",
        "keep.log",
        "deep/b.log",
        "root_only",
        "deep/root_only",
        "build/x",
        "deep/build",
        "logs/x/y.txt",
        "logs/z.txt",
        "doc/a/b/c.md",
        "doc/c.md",
        "lit*",
        "litX",
        "file1",
        "file9",
        "#hash",
        "s p",
    ]
    write(dir, dict.fromkeys(files, ""))
    write(dir, {"sub/inner.tmp": "", "sub/outer.tmp": "", "sub/.gitignore": "*.tmp\n!outer.tmp\n"})
    ignore = "*.log\n!keep.log\n/root_only\nbuild/\nlogs/**/*.txt\ndoc/**/c.md\nlit\\*\nfile[0-5]\n\\#hash\ns\\ p\n"
    write(dir, {".gitignore": ignore})
    scan = await store.scan(dir, None, "main", excludes=["*.md"])
    expected = {
        ".gitignore",
        "keep.log",
        "deep/root_only",
        "deep/build",
        "litX",
        "file9",
        "sub/.gitignore",
        "sub/outer.tmp",
    }
    assert set(scan.files) == expected


async def test_tracked_files_are_read_from_any_version_of_the_repos_index(store, dir):
    write(dir, {".gitignore": "*.log\n", "sub/a.log": "", "sub/b.log": "", "c.log": ""})
    git_in(dir, "init", "-q")
    git_in(dir, "add", "-f", "sub/a.log")
    git_in(dir, "add", "-f", "-N", "c.log")
    for version in ("2", "3", "4"):
        git_in(dir, "update-index", "--index-version", version)
        assert set((await store.scan(dir, None, "main")).files) == {".gitignore", "sub/a.log", "c.log"}, version
        assert set((await store.scan(dir / "sub", None, "sub")).files) == {"a.log", "b.log"}, version
