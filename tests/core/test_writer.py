"""core/writer.py: the only way to change a log; writes are live but uncommitted until commit()."""

import asyncio
import random
import subprocess

import pytest

from llvim.core import Author, Committing, GitError, Log, Message, Moved, Released, Request
from llvim.core.live import records


@pytest.fixture
def log():
    return Log("p")


def messages(log: Log, at: str | None = None) -> list[Message]:
    return list(log.read(at).messages)


async def test_append_gives_ids_in_order(log):
    async with await log.claim(Request(0)) as writer:
        assert [writer.append(b"a"), writer.append(b"b")] == [0, 1]
        assert messages(log) == [Message(0, b"a"), Message(1, b"b")]


async def test_extend_adds_to_the_end_of_a_message(log):
    async with await log.claim(Request(0)) as writer:
        id = writer.append(b"a")
        writer.extend(id, b"b")
        assert messages(log) == [Message(id, b"ab")]


async def test_replace_and_remove_change_one_message(log):
    async with await log.claim(Request(0)) as writer:
        a, b = writer.append(b"a"), writer.append(b"b")
        writer.replace(a, b"A")
        writer.remove(b)
        assert messages(log) == [Message(a, b"A")]


async def test_changing_a_missing_message_raises(log):
    async with await log.claim(Request(0)) as writer:
        changes = [
            ("extend", lambda: writer.extend(9, b"x")),
            ("replace", lambda: writer.replace(9, b"x")),
            ("remove", lambda: writer.remove(9)),
        ]
        for name, change in changes:
            with pytest.raises(KeyError):
                change()
                pytest.fail(f"{name} of a missing message did not raise")
        assert messages(log) == []


async def test_ids_are_never_reused_after_a_remove(log):
    async with await log.claim(Request(0)) as writer:
        writer.remove(writer.append(b"a"))
        await writer.commit()
    async with await log.claim(Request(0)) as writer:
        assert writer.append(b"b") == 1


async def test_commit_makes_the_writes_permanent(log):
    async with await log.claim(Request(0)) as writer:
        writer.append(b"a")
        commit = await writer.commit()
    assert log.head() == commit
    assert messages(log) == messages(log, commit) == [Message(0, b"a")]
    assert log.read().uncommitted == ()


async def test_release_discards_what_is_uncommitted(log):
    async with await log.claim(Request(0)) as writer:
        writer.append(b"kept")
        await writer.commit()
        writer.append(b"lost")
    assert messages(log) == [Message(0, b"kept")]


async def test_leaving_async_with_on_an_error_releases(log):
    with pytest.raises(ZeroDivisionError):
        async with await log.claim(Request(0)):
            1 / 0
    (await log.claim(Request(0), timeout=0)).release()


async def test_a_released_writer_refuses_to_write(log):
    writer = await log.claim(Request(0))
    writer.release()
    writer.release()
    with pytest.raises(Released):
        writer.append(b"a")
    with pytest.raises(Released):
        await writer.commit()


async def test_a_commit_with_nothing_new_keeps_the_head(log):
    async with await log.claim(Request(0)) as writer:
        writer.append(b"a")
        first = await writer.commit()
        assert await writer.commit() == first


async def test_the_first_commit_of_an_empty_log_is_made_even_without_writes(log):
    async with await log.claim(Request(0)) as writer:
        commit = await writer.commit()
    assert log.head() == commit
    assert messages(log) == []


async def test_commit_fails_if_something_else_moved_the_head(log):
    async with await log.claim(Request(0)) as writer:
        writer.append(b"a")
        first = await writer.commit()
        writer.append(b"b")
        await writer.commit()
        subprocess.run(["git", "--git-dir", str(log.repo), "update-ref", log.ref, first], check=True)
        writer.append(b"c")
        with pytest.raises(Moved):
            await writer.commit()
    assert log.head() == first


async def test_writes_made_while_a_commit_runs_stay_uncommitted_and_seen(log):
    async with await log.claim(Request(0)) as writer:
        a = writer.append(b"a")
        committing = asyncio.create_task(writer.commit())
        await asyncio.sleep(0)
        writer.extend(a, b"+")
        b = writer.append(b"b")
        commit = await committing
        assert messages(log, commit) == [Message(a, b"a")]
        assert log.read().uncommitted == (Message(a, b"a+"), Message(b, b"b"))
        assert messages(log, await writer.commit()) == [Message(a, b"a+"), Message(b, b"b")]


async def test_restore_and_a_second_commit_are_refused_while_a_commit_runs(log):
    async with await log.claim(Request(0)) as writer:
        first = await writer.commit()
        writer.append(b"a")
        committing = asyncio.create_task(writer.commit())
        await asyncio.sleep(0)
        with pytest.raises(Committing):
            writer.restore(first)
        with pytest.raises(Committing):
            await writer.commit()
        await committing
        assert messages(log) == [Message(0, b"a")]


async def test_restore_brings_back_an_old_state_on_top_of_history(log):
    async with await log.claim(Request(0)) as writer:
        writer.append(b"a")
        old = await writer.commit()
        writer.append(b"b")
        later = await writer.commit()
        writer.restore(old)
        assert messages(log) == [Message(0, b"a")]
        restored = await writer.commit()
        assert writer.append(b"c") == 2
    history = subprocess.run(["git", "--git-dir", str(log.repo), "rev-list", restored], capture_output=True, text=True)
    assert history.stdout.split() == [restored, later, old]
    assert messages(log, later) == [Message(0, b"a"), Message(1, b"b")]


async def test_readers_see_exactly_what_the_writer_commits(log):
    rng = random.Random(7)
    async with await log.claim(Request(0)) as writer:
        commits = [await writer.commit()]
        for step in range(60):
            ids = [message.id for message in log.read().messages]
            choice = rng.choice(["append", "extend", "replace", "remove", "restore"])
            if choice == "append" or not ids:
                writer.append(bytes([rng.randrange(256)]))
            elif choice == "extend":
                writer.extend(rng.choice(ids), b"+")
            elif choice == "replace":
                writer.replace(rng.choice(ids), b"=")
            elif choice == "remove":
                writer.remove(rng.choice(ids))
            else:
                writer.restore(rng.choice(commits))
            if rng.random() < 0.25:
                live = log.read().messages
                commits.append(await writer.commit())
                assert log.read(commits[-1]).messages == live, f"step {step}, after {choice}"


async def test_outranked_when_a_higher_priority_waits(log, wait_until):
    holder = await log.claim(Request(1))
    waiters = []
    for priority, outranked in [(1, False), (2, True)]:
        waiters.append(asyncio.create_task(log.claim(Request(priority))))
        await wait_until(log, lambda: len(log.queue()) == len(waiters) + 1)
        assert holder.outranked() is outranked, f"waiter of priority {priority}"
    holder.release()
    async with asyncio.timeout(5):
        for claimed in asyncio.as_completed(waiters):
            (await claimed).release()


async def test_outranked_changed_comes_when_someone_joins_the_queue(log):
    async with await log.claim(Request(1)) as holder:
        await holder.outranked_changed()
        waiter = asyncio.create_task(log.claim(Request(2)))
        async with asyncio.timeout(5):
            await holder.outranked_changed()
        assert holder.outranked()
    async with asyncio.timeout(5):
        (await waiter).release()


async def test_outranked_changed_returns_at_once_the_first_time_and_then_waits_for_a_change(log):
    async with await log.claim(Request(1)) as holder:
        async with asyncio.timeout(1):
            await holder.outranked_changed()
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(holder.outranked_changed(), 0.05)


async def test_a_killed_writer_keeps_only_what_it_committed(log, spawn):
    child = spawn(
        "import asyncio, time\n"
        "from llvim.core.log import Log, Request\n"
        "async def write():\n"
        "    w = await Log('p').claim(Request(0))\n"
        "    w.append(b'kept'); await w.commit(); w.append(b'lost')\n"
        "    print('ready', flush=True)\n"
        "    time.sleep(60)\n"
        "asyncio.run(write())\n"
    )
    child.kill()
    child.wait()
    assert messages(log) == [Message(0, b"kept")]


def git_show(log: Log, commit: str, format: str) -> str:
    command = ["git", "--git-dir", str(log.repo), "show", "-s", f"--format={format}", commit]
    return subprocess.run(command, capture_output=True, text=True).stdout


async def test_a_commit_says_who_wrote_it_and_why(log):
    async with await log.claim(Request(0)) as writer:
        writer.append(b"a")
        commit = await writer.commit(author=Author("gpt-5", "model@llvim"), message="reply\n\nwith a body")
    shown = git_show(log, commit, "%an <%ae>|%cn <%ce>|%B")
    assert shown == "gpt-5 <model@llvim>|llvim <llvim>|reply\n\nwith a body\n"


async def test_a_commit_with_no_author_is_llvims(log):
    async with await log.claim(Request(0)) as writer:
        commit = await writer.commit()
    assert git_show(log, commit, "%an <%ae>|%B") == "llvim <llvim>|\n"


async def test_a_commit_git_refuses_for_another_reason_is_not_moved_and_can_be_tried_again(log):
    async with await log.claim(Request(0)) as writer:
        writer.append(b"a")
        first = await writer.commit()
        stale = log.repo / "refs" / "heads" / "main.lock"
        stale.write_text("")
        writer.append(b"b")
        with pytest.raises(GitError, match="main.lock"):
            await writer.commit()
        assert log.head() == first
        assert log.read().uncommitted == (Message(1, b"b"),)
        stale.unlink()
        assert messages(log, await writer.commit()) == [Message(0, b"a"), Message(1, b"b")]


async def test_a_cancelled_commit_still_leaves_the_writer_where_git_put_the_head(log):
    async with await log.claim(Request(0)) as writer:
        await writer.commit()
        for step in range(1000):
            writer.append(f"{step}".encode())
            committing = asyncio.create_task(writer.commit())
            await asyncio.sleep(step / 10_000)
            committing.cancel()
            await asyncio.gather(committing, return_exceptions=True)
            await asyncio.sleep(0.005)  # a git the cancel left running would move the head by now
            assert log.head() == writer._base, f"cancelled after {step / 10} ms, the writer lost track of the head"
            if not committing.cancelled():
                break  # the commit beat the cancel; waiting longer tests nothing new
        await writer.commit()
    assert messages(log) == [Message(id, f"{id}".encode()) for id in range(step + 1)]


async def test_put_files_are_committed_and_kept_by_later_commits(log):
    async with await log.claim(Request(0)) as writer:
        writer.put("a", b"1")
        writer.put("sub/b", b"2")
        first = await writer.commit()
        writer.append(b"message")
        second = await writer.commit()
    assert log.files(first) == log.files(second) == ["a", "sub/b"]
    assert log.file("sub/b", second) == b"2"


async def test_a_commit_with_only_file_changes_is_a_new_commit(log):
    async with await log.claim(Request(0)) as writer:
        first = await writer.commit()
        writer.put("a", b"")
        second = await writer.commit()
    assert second != first
    assert log.files(first) == [] and log.files(second) == ["a"]


async def test_put_of_none_removes_a_file_or_a_folder(log):
    async with await log.claim(Request(0)) as writer:
        for path in ["a", "b", "f/x", "f/y/z"]:
            writer.put(path, b"")
        await writer.commit()
        writer.put("a", None)
        writer.put("f", None)
        assert log.files(await writer.commit()) == ["b"]


async def test_a_later_put_to_a_path_replaces_an_earlier_one(log):
    async with await log.claim(Request(0)) as writer:
        writer.put("a", b"first")
        writer.put("a", b"second")
        writer.put("f/x", b"")
        writer.put("f", b"now a file")
        await writer.commit()
    assert (log.files(), log.file("a"), log.file("f")) == (["a", "f"], b"second", b"now a file")


async def tree_of(log: Log, files: dict[str, bytes]) -> str:
    """A tree holding `files`, made the way a caller makes one: put, committed, and read back."""
    async with await log.claim(Request(0)) as writer:
        for path, content in files.items():
            writer.put(f"made/{path}", content)
        await writer.commit()
        tree = log.tree("made")
        writer.put("made", None)
        await writer.commit()
    return tree


async def test_put_tree_sets_a_folder_and_puts_inside_it_apply_on_top(log):
    tree = await tree_of(log, {"x": b"x", "y": b"y"})
    async with await log.claim(Request(0)) as writer:
        writer.put("snap/old", b"")
        writer.put_tree("snap", tree)
        writer.put("snap/x", b"changed")
        writer.put_tree("copy", tree)
        writer.put_tree("copy", None)
        await writer.commit()
    assert log.files() == ["snap/x", "snap/y"]
    assert log.file("snap/x") == b"changed"


async def test_put_tree_of_the_root_replaces_every_file(log):
    tree = await tree_of(log, {"x": b""})
    async with await log.claim(Request(0)) as writer:
        writer.put("old", b"")
        await writer.commit()
        writer.put_tree("", tree)
        await writer.commit()
    assert log.files() == ["x"]


async def test_put_refuses_a_bad_path_and_put_tree_an_unknown_tree(log):
    async with await log.claim(Request(0)) as writer:
        for put in [lambda: writer.put("", b""), lambda: writer.put("../a", b""), lambda: writer.put_tree("a", "x")]:
            with pytest.raises(ValueError):
                put()
                pytest.fail("accepted")


async def test_a_released_writer_refuses_to_put_files(log):
    writer = await log.claim(Request(0))
    writer.release()
    for put in [lambda: writer.put("a", b""), lambda: writer.put_tree("a", None)]:
        with pytest.raises(Released):
            put()


async def test_file_changes_made_while_a_commit_runs_go_in_the_next_one(log):
    async with await log.claim(Request(0)) as writer:
        writer.put("a", b"1")
        committing = asyncio.create_task(writer.commit())
        await asyncio.sleep(0)
        writer.put("b", b"2")
        first = await committing
        assert log.files(first) == ["a"]
        journal = (log.dir / f"journal.{writer._key}").read_bytes()
        assert [op for op, _, _ in records(journal)] == [b"B", b"F"], "the fresh journal lacks the late put"
        assert log.files(await writer.commit()) == ["a", "b"]


async def test_file_changes_of_a_failed_commit_are_kept_under_later_ones(log):
    async with await log.claim(Request(0)) as writer:
        await writer.commit()
        stale = log.repo / "refs" / "heads" / "main.lock"
        stale.write_text("")
        writer.put("a", b"failed")
        writer.put("b", b"failed")
        committing = asyncio.create_task(writer.commit())
        await asyncio.sleep(0)
        writer.put("b", b"later")
        with pytest.raises(GitError):
            await committing
        stale.unlink()
        await writer.commit()
    assert [log.file("a"), log.file("b")] == [b"failed", b"later"]


async def test_restore_brings_back_the_files_too(log):
    async with await log.claim(Request(0)) as writer:
        empty = await writer.commit()
        writer.put("a", b"1")
        old = await writer.commit()
        writer.put("a", b"2")
        writer.put("b", b"")
        await writer.commit()
        writer.restore(old)
        assert log.files(await writer.commit()) == ["a"]
        assert log.file("a") == b"1"
        writer.restore(empty)
        assert log.files(await writer.commit()) == []


async def test_a_restore_to_the_same_files_commits_no_file_change(log):
    async with await log.claim(Request(0)) as writer:
        writer.put("a", b"")
        old = await writer.commit()
        writer.append(b"m")
        await writer.commit()
        writer.restore(old)
        restored = await writer.commit()
    assert log.tree(at=restored) == log.tree(at=old)


async def test_file_changes_are_in_the_journal_as_they_are_made(log):
    async with await log.claim(Request(0)) as writer:
        writer.put("a", b"content")
        writer.put_tree("f", None)
        journal = (log.dir / f"journal.{writer._key}").read_bytes()
    blob = subprocess.run(
        ["git", "--git-dir", str(log.repo), "hash-object", "--stdin"], input=b"content", capture_output=True
    ).stdout.strip()
    assert [(op, payload) for op, _, payload in records(journal)][1:] == [(b"F", b"a\0" + blob), (b"T", b"f\0")]
