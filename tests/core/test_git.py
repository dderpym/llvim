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


def raw(repo, *args: str, **env: str) -> str:
    command = ["git", "--git-dir", str(repo), *args]
    done = subprocess.run(command, input="", capture_output=True, text=True, check=True, env=git.env() | env)
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
