"""core/writer.py: the only way to change a log; writes are live but uncommitted until commit()."""

import asyncio
import random
import subprocess

import pytest

from llvim.core.log import Author, Log, Message, Request
from llvim.core.writer import Moved


@pytest.fixture
def log():
    return Log("p")


def messages(log: Log, at: str | None = None) -> list[Message]:
    return list(log.read(at).messages)


async def test_append_gives_ids_in_order(log):
    async with log.claim(Request(0)) as writer:
        assert [writer.append(b"a"), writer.append(b"b")] == [0, 1]
        assert messages(log) == [Message(0, b"a"), Message(1, b"b")]


async def test_extend_adds_to_the_end_of_a_message(log):
    async with log.claim(Request(0)) as writer:
        id = writer.append(b"a")
        writer.extend(id, b"b")
        assert messages(log) == [Message(id, b"ab")]


async def test_replace_and_remove_change_one_message(log):
    async with log.claim(Request(0)) as writer:
        a, b = writer.append(b"a"), writer.append(b"b")
        writer.replace(a, b"A")
        writer.remove(b)
        assert messages(log) == [Message(a, b"A")]


async def test_changing_a_missing_message_raises(log):
    async with log.claim(Request(0)) as writer:
        for name, change in [("extend", lambda: writer.extend(9, b"x")), ("replace", lambda: writer.replace(9, b"x")), ("remove", lambda: writer.remove(9))]:
            with pytest.raises(KeyError):
                change()
                pytest.fail(f"{name} of a missing message did not raise")
        assert messages(log) == []


async def test_ids_are_never_reused_after_a_remove(log):
    async with log.claim(Request(0)) as writer:
        writer.remove(writer.append(b"a"))
        await writer.commit()
    async with log.claim(Request(0)) as writer:
        assert writer.append(b"b") == 1


async def test_commit_makes_the_writes_permanent(log):
    async with log.claim(Request(0)) as writer:
        writer.append(b"a")
        commit = await writer.commit()
    assert log.head() == commit
    assert messages(log) == messages(log, commit) == [Message(0, b"a")]
    assert log.read().uncommitted == ()


async def test_release_discards_what_is_uncommitted(log):
    async with log.claim(Request(0)) as writer:
        writer.append(b"kept")
        await writer.commit()
        writer.append(b"lost")
    assert messages(log) == [Message(0, b"kept")]


async def test_leaving_async_with_on_an_error_releases(log):
    with pytest.raises(ZeroDivisionError):
        async with log.claim(Request(0)):
            1 / 0
    (await log.claim(Request(0), timeout=0)).release()


async def test_a_released_writer_refuses_to_write(log):
    writer = await log.claim(Request(0))
    writer.release()
    writer.release()
    with pytest.raises(RuntimeError):
        writer.append(b"a")
    with pytest.raises(RuntimeError):
        await writer.commit()


async def test_a_commit_with_nothing_new_keeps_the_head(log):
    async with log.claim(Request(0)) as writer:
        writer.append(b"a")
        first = await writer.commit()
        assert await writer.commit() == first


async def test_the_first_commit_of_an_empty_log_is_made_even_without_writes(log):
    async with log.claim(Request(0)) as writer:
        commit = await writer.commit()
    assert log.head() == commit
    assert messages(log) == []


async def test_commit_fails_if_something_else_moved_the_head(log):
    async with log.claim(Request(0)) as writer:
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
    async with log.claim(Request(0)) as writer:
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
    async with log.claim(Request(0)) as writer:
        first = await writer.commit()
        writer.append(b"a")
        committing = asyncio.create_task(writer.commit())
        await asyncio.sleep(0)
        with pytest.raises(RuntimeError):
            writer.restore(first)
        with pytest.raises(RuntimeError):
            await writer.commit()
        await committing
        assert messages(log) == [Message(0, b"a")]


async def test_restore_brings_back_an_old_state_on_top_of_history(log):
    async with log.claim(Request(0)) as writer:
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
    async with log.claim(Request(0)) as writer:
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
    return subprocess.run(["git", "--git-dir", str(log.repo), "show", "-s", f"--format={format}", commit], capture_output=True, text=True).stdout


async def test_a_commit_says_who_wrote_it_and_why(log):
    async with log.claim(Request(0)) as writer:
        writer.append(b"a")
        commit = await writer.commit(author=Author("gpt-5", "model@llvim"), message="reply\n\nwith a body")
    assert git_show(log, commit, "%an <%ae>|%cn <%ce>|%B") == "gpt-5 <model@llvim>|llvim <llvim>|reply\n\nwith a body\n"


async def test_a_commit_with_no_author_is_llvims(log):
    async with log.claim(Request(0)) as writer:
        commit = await writer.commit()
    assert git_show(log, commit, "%an <%ae>|%B") == "llvim <llvim>|\n"


async def test_an_author_git_cannot_record_is_refused(log):
    for name, email in [("a <b>", "x"), ("a\nb", "x"), ("a", "x>y"), ("a", "x\ny"), ("", "x")]:
        with pytest.raises(ValueError):
            Author(name, email)
            pytest.fail(f"accepted {name!r} <{email!r}>")


async def test_a_commit_git_refuses_for_another_reason_is_not_moved_and_can_be_tried_again(log):
    async with log.claim(Request(0)) as writer:
        writer.append(b"a")
        first = await writer.commit()
        stale = log.repo / "refs" / "heads" / "main.lock"
        stale.write_text("")
        writer.append(b"b")
        with pytest.raises(RuntimeError, match="main.lock"):
            await writer.commit()
        assert log.head() == first
        assert log.read().uncommitted == (Message(1, b"b"),)
        stale.unlink()
        assert messages(log, await writer.commit()) == [Message(0, b"a"), Message(1, b"b")]
