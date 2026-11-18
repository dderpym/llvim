"""core/git.py: the repo of a project, and the only code that runs git or knows how a log is laid out in it."""

import asyncio
import subprocess
import time

import pytest

from llvim.core import git
from llvim.core.git import LLVIM, Author, GitError

REF = "refs/heads/main"
IDENTITY = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t"}


@pytest.fixture
def repo(tmp_path):
    repo = tmp_path / "repo"
    git.init(repo)
    (repo / "llvim").mkdir()
    return repo


def raw(repo, *args: str, input: str = "", **env: str) -> str:
    command = ["git", "--git-dir", str(repo), *args]
    done = subprocess.run(command, input=input, capture_output=True, text=True, check=True, env=git.env() | env)
    return done.stdout.strip()


async def commit(repo, changes, base=None, where=None, bucket=500, next_id=None) -> str:
    next_id = max(changes, default=-1) + 1 if next_id is None else next_id
    where = {} if where is None else where
    made = await git.commit(repo, REF, base, changes, next_id, where, bucket, LLVIM, "")
    assert made is not None
    return made


def read(repo, commit: str, last: git.Tree | None = None) -> git.Tree:
    return git.Tree.read(git.Objects(repo), commit, last)


async def test_messages_are_stored_in_buckets_of_n(repo):
    made = await commit(repo, dict.fromkeys(range(5), b"x"), bucket=2)
    paths = raw(repo, "ls-tree", "-r", "--name-only", made).split()
    assert paths == ["messages/0/0", "messages/0/1", "messages/2/2", "messages/2/3", "messages/4/4", "next"]


async def test_a_commit_moves_the_ref_and_reads_back_as_written(repo):
    made = await commit(repo, {0: b"a", 1: b""}, next_id=7)
    assert git.target(repo, REF) == made
    tree = read(repo, made)
    assert (tree.contents, tree.next_id, tree.where) == ({0: b"a", 1: b""}, 7, {0: "0", 1: "0"})


async def test_a_commit_rewrites_only_the_buckets_it_changes(repo):
    where = {}
    before = await commit(repo, dict.fromkeys(range(6), b"x"), where=where, bucket=2)
    after = await commit(repo, {0: b"xy"}, base=before, where=where, bucket=2, next_id=6)
    for bucket, same in [("0", False), ("2", True), ("4", True)]:
        trees = [raw(repo, "rev-parse", f"{commit}:messages/{bucket}") for commit in (before, after)]
        assert (trees[0] == trees[1]) is same, bucket


async def test_a_new_bucket_size_leaves_old_messages_where_they_are(repo):
    where = {}
    first = await commit(repo, dict.fromkeys(range(4), b"x"), where=where, bucket=2)
    made = await commit(repo, {1: b"y", 2: None, 4: b"z"}, base=first, where=where, bucket=3)
    paths = raw(repo, "ls-tree", "-r", "--name-only", made).split()
    assert paths == ["messages/0/0", "messages/0/1", "messages/2/3", "messages/3/4", "next"]
    assert where == read(repo, made).where


async def test_reading_on_top_of_an_earlier_read_agrees_with_a_fresh_read(repo):
    where = {}
    first = await commit(repo, dict.fromkeys(range(6), b"x"), where=where, bucket=2)
    second = await commit(repo, {0: b"", 3: None, 6: b"y"}, base=first, where=where, bucket=2)
    assert read(repo, second, last=read(repo, first)) == read(repo, second)


async def test_a_commit_on_a_moved_ref_returns_none_and_leaves_the_ref(repo):
    first = await commit(repo, {0: b"a"})
    second = await commit(repo, {1: b"b"}, base=first)
    assert await git.commit(repo, REF, first, {2: b"c"}, 3, {}, 500, LLVIM, "") is None
    assert git.target(repo, REF) == second


async def test_a_ref_git_will_not_move_raises_git_error_and_leaves_no_scratch_ref(repo):
    first = await commit(repo, {0: b"a"})
    (repo / "refs" / "heads" / "main.lock").write_text("")
    with pytest.raises(GitError, match="main.lock"):
        await commit(repo, {1: b"b"}, base=first)
    assert git.target(repo, REF) == first
    assert raw(repo, "for-each-ref", "refs/llvim/") == ""


async def test_a_failed_fast_import_raises_git_error(repo):
    with pytest.raises(GitError):
        await commit(repo, {0: b"a"}, base="1" * 40)


def test_a_repo_git_cannot_make_raises_git_error(tmp_path):
    (tmp_path / "file").write_text("")
    with pytest.raises(GitError):
        git.init(tmp_path / "file" / "repo")


async def test_the_target_of_a_packed_ref_is_read(repo):
    made = await commit(repo, {0: b"a"})
    raw(repo, "pack-refs", "--all")
    assert not (repo / REF).exists()
    assert git.target(repo, REF) == made
    assert git.target(repo, "refs/heads/other") is None


def test_an_author_git_cannot_record_is_refused():
    bad = [("a <b>", "x"), ("a\nb", "x"), ("a\0b", "x"), ("a", "x>y"), ("a", "x\ny"), ("a", "x\0y"), ("", "x")]
    for name, email in bad:
        with pytest.raises(ValueError):
            Author(name, email)
            pytest.fail(f"accepted {name!r} <{email!r}>")


async def test_the_users_git_settings_and_environment_do_not_reach_the_repo(tmp_path, monkeypatch):
    marker = tmp_path / "a hook ran"
    hooks = tmp_path / "hooks"
    (hooks / "hooks").mkdir(parents=True)
    for folder in (hooks, hooks / "hooks"):
        hook = folder / "reference-transaction"
        hook.write_text(f"#!/bin/sh\ntouch '{marker}'\nexit 1\n")
        hook.chmod(0o755)
    settings = tmp_path / "gitconfig"
    settings.write_text(f"[core]\n\thooksPath = {hooks}\n[init]\n\ttemplateDir = {hooks}\n[commit]\n\tgpgSign = true\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(settings))
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "nowhere"))
    monkeypatch.setenv("GIT_NAMESPACE", "elsewhere")
    repo = tmp_path / "repo"
    git.init(repo)
    made = await commit(repo, {0: b"a"})
    assert git.target(repo, REF) == made
    assert read(repo, made).contents == {0: b"a"}
    assert not marker.exists()
    assert not (repo / "hooks" / "reference-transaction").exists()


def count(repo) -> dict[str, int]:
    out = raw(repo, "count-objects", "-v")
    return {key: int(value) for key, value in (line.split(": ") for line in out.splitlines()) if value.isdigit()}


async def settled(repo, tidy) -> None:
    deadline = time.monotonic() + 5
    while not tidy(count(repo)):
        assert time.monotonic() < deadline, f"never tidied: {count(repo)}"
        await asyncio.sleep(0.01)


async def test_packs_and_loose_objects_are_merged_in_the_background_as_commits_add_them(tmp_path, monkeypatch):
    monkeypatch.setattr(git, "PACKS", 4)
    monkeypatch.setattr(git, "LOOSE", -1)
    for name, per_commit, tidy in [
        ("small commits, which leave loose objects", 1, lambda count: count["count"] < 100),
        ("large commits, which leave a pack each", 120, lambda count: count["packs"] <= 4),
    ]:
        repo = tmp_path / name
        git.init(repo)
        (repo / "llvim").mkdir()
        head, where = None, {}
        for step in range(30):
            ids = range(step * per_commit, (step + 1) * per_commit)
            head = await commit(repo, dict.fromkeys(ids, b"x"), base=head, where=where)
        await settled(repo, tidy)
        assert len(read(repo, head).contents) == 30 * per_commit, name


async def test_repacking_drops_scratch_refs_left_by_commits_that_died(repo):
    tree = raw(repo, "mktree", "--missing")
    for name, age in [("old", git.SCRATCH_AGE + 60), ("fresh", 0)]:
        date = f"{int(time.time()) - age} +0000"
        dated = IDENTITY | {"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
        made = raw(repo, "commit-tree", tree, "-m", name, **dated)
        raw(repo, "update-ref", f"refs/llvim/scratch/{name}", made)
    git.repack(repo)
    assert raw(repo, "for-each-ref", "--format=%(refname)", "refs/llvim/") == "refs/llvim/scratch/fresh"


async def test_a_commit_applies_file_changes_in_order_on_top_of_its_base(repo):
    blob = raw(repo, "hash-object", "-w", "--stdin")
    tree = raw(repo, "mktree", input=f"100644 blob {blob}\tx\n")
    first = await git.commit(repo, REF, None, {}, 0, {}, 500, LLVIM, "", {"old": ("100644", blob)})
    files = {
        "t": ("040000", tree),
        "t/y": ("100644", blob),
        'a "quoted" path': ("100644", blob),
        "old": None,
    }
    made = await git.commit(repo, REF, first, {}, 0, {}, 500, LLVIM, "", files)
    paths = raw(repo, "ls-tree", "-r", "--name-only", "-z", made).rstrip("\0").split("\0")
    assert paths == ['files/a "quoted" path', "files/t/x", "files/t/y", "next"]


async def test_a_commit_with_no_file_changes_keeps_the_files_of_its_base(repo):
    blob = raw(repo, "hash-object", "-w", "--stdin")
    first = await git.commit(repo, REF, None, {}, 0, {}, 500, LLVIM, "", {"a": ("100644", blob)})
    second = await commit(repo, {0: b"m"}, base=first)
    assert raw(repo, "rev-parse", f"{first}:files") == raw(repo, "rev-parse", f"{second}:files")


async def test_removing_the_root_removes_every_file(repo):
    blob = raw(repo, "hash-object", "-w", "--stdin")
    first = await git.commit(repo, REF, None, {}, 0, {}, 500, LLVIM, "", {"a/b": ("100644", blob)})
    made = await git.commit(repo, REF, first, {}, 0, {}, 500, LLVIM, "", {"": None, "c": ("100644", blob)})
    assert raw(repo, "ls-tree", "-r", "--name-only", made).split() == ["files/c", "next"]


def test_walk_gives_every_entry_of_a_tree_but_its_folders(repo):
    blob = raw(repo, "hash-object", "-w", "--stdin")
    inner = raw(repo, "mktree", input=f"100644 blob {blob}\tb\n120000 blob {blob}\tlink\n")
    tree = raw(repo, "mktree", "--missing", input=f"040000 tree {inner}\tdir\n160000 commit {'1' * 40}\tsub\n")
    assert list(git.walk(git.Objects(repo), tree)) == [
        ("dir/b", "100644", blob),
        ("dir/link", "120000", blob),
        ("sub", "160000", "1" * 40),
    ]


def test_written_blobs_are_in_the_repo_in_the_order_given(repo, tmp_path):
    (tmp_path / "file").write_text("from a file")
    (tmp_path / "a\nname").write_text("odd name")
    (tmp_path / "link").symlink_to(tmp_path / "file")
    sources = [b"content", tmp_path / "file", tmp_path / "a\nname", tmp_path / "link", b""]
    ids = git.write_blobs(repo, sources)
    assert [raw(repo, "cat-file", "blob", id) for id in ids] == [
        "content",
        "from a file",
        "odd name",
        "from a file",
        "",
    ]
    assert git.write_blobs(repo, []) == []


def test_a_file_that_cannot_be_read_is_not_stored(repo, tmp_path):
    with pytest.raises(GitError):
        git.write_blobs(repo, [tmp_path / "missing"])


def test_a_tree_is_made_with_the_folders_its_paths_need(repo):
    a, b = git.write_blobs(repo, [b"a", b"b"])
    inner = git.write_tree(repo, {"x": ("100644", a)})
    entries = {"top": ("100755", a), "deep/er/f": ("100644", b), "link": ("120000", b), "sub": ("040000", inner)}
    tree = git.write_tree(repo, entries)
    listing = raw(repo, "ls-tree", "-r", "--format=%(objectmode) %(path)", tree).splitlines()
    assert listing == ["100644 deep/er/f", "120000 link", "100644 sub/x", "100755 top"]


def test_a_tree_of_nothing_is_none(repo):
    assert git.write_tree(repo, {}) is None


def test_a_tree_git_cannot_make_is_refused(repo):
    (blob,) = git.write_blobs(repo, [b""])
    cases = [
        ("a path under a file", {"a": ("100644", blob), "a/b": ("100644", blob)}, ValueError),
        ("a file over a folder", {"a/b": ("100644", blob), "a": ("100644", blob)}, ValueError),
        ("a bad path", {"../a": ("100644", blob)}, ValueError),
        ("a missing object", {"a": ("100644", "1" * 40)}, GitError),
    ]
    for case, entries, error in cases:
        with pytest.raises(error):
            git.write_tree(repo, entries)
            pytest.fail(case)


def test_a_path_that_cannot_name_a_file_is_refused():
    for path in ["", "/a", "a/", "a//b", ".", "a/..", ".git", "x/.git/y", "a\nb", "a\0b"]:
        with pytest.raises(ValueError):
            git.file_path(path)
            pytest.fail(f"accepted {path!r}")
    assert git.file_path("", root=True) == ""
    assert git.file_path("a b/.c") == "a b/.c"
