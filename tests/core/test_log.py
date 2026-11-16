"""core/log.py: a view of one log; anyone reads it and watches it, and it hands out one Writer at a time."""

import asyncio
import fcntl
import json
import random
import subprocess
import time

import pytest

from llvim.core import log as log_module
from llvim.core.log import RECORD, Log, Message, Request, Snapshot

HOLD = """
import asyncio, time
from llvim.core.log import Log, Request
async def hold():
    writer = await Log("p").claim(Request(0))
    writer.append(b"uncommitted")
    print("ready", flush=True)
    time.sleep(60)
asyncio.run(hold())
"""


async def committed(log: Log, *contents: bytes) -> str:
    async with log.claim(Request(0)) as writer:
        for content in contents:
            writer.append(content)
        return await writer.commit()


def messages(log: Log, at: str | None = None) -> list[Message]:
    return list(log.read(at).messages)


def test_a_new_log_is_empty():
    log = Log("p")
    assert log.head() is None
    assert log.read() == Snapshot(None, ())


async def test_reading_at_a_commit_gives_exactly_what_it_holds():
    log = Log("p")
    first = await committed(log, b"a")
    await committed(log, b"b")
    async with log.claim(Request(0)) as writer:
        writer.append(b"c")
        assert log.read(first) == Snapshot(first, (Message(0, b"a"),))
        assert messages(log, log.head()) == [Message(0, b"a"), Message(1, b"b")]


async def test_reading_an_unknown_commit_raises():
    log = Log("p")
    await committed(log, b"a")
    for bad in ("0" * 40, "nonsense", "-x", "a\nb"):
        with pytest.raises(ValueError):
            log.read(bad)
            pytest.fail(f"read {bad!r}")


async def test_read_shows_the_holders_uncommitted_writes_as_they_grow():
    log = Log("p")
    async with log.claim(Request(0)) as writer:
        id = writer.append(b"hel")
        assert messages(log) == [Message(id, b"hel")]
        writer.extend(id, b"lo")
        assert messages(Log("p")) == [Message(id, b"hello")]


async def test_a_snapshot_says_what_is_uncommitted_and_what_was_removed():
    log = Log("p")
    head = await committed(log, b"a", b"b", b"c")
    async with log.claim(Request(0)) as writer:
        writer.extend(0, b"+")
        writer.remove(1)
        writer.remove(writer.append(b"gone again"))
        writer.replace(2, b"c")
        new = writer.append(b"d")
        assert log.read() == Snapshot(
            head,
            (Message(0, b"a+"), Message(2, b"c"), Message(new, b"d")),
            uncommitted=(Message(0, b"a+"), Message(new, b"d")),
            removed=(Message(1, b"b"),),
        )


async def test_a_restore_shows_as_what_it_changes_against_the_head():
    log = Log("p")
    old = await committed(log, b"a")
    async with log.claim(Request(0)) as writer:
        writer.replace(0, b"A")
        writer.append(b"b")
        head = await writer.commit()
        writer.restore(old)
        assert log.read() == Snapshot(head, (Message(0, b"a"),), uncommitted=(Message(0, b"a"),), removed=(Message(1, b"b"),))


async def test_a_holder_in_another_process_is_seen_live(spawn):
    spawn(HOLD)
    assert Log("p").read().uncommitted == (Message(0, b"uncommitted"),)


async def test_the_writes_of_a_dead_holder_are_gone(spawn):
    log = Log("p")
    await committed(log, b"kept")
    child = spawn(HOLD)
    child.kill()
    child.wait()
    assert messages(log) == [Message(0, b"kept")]


async def test_changes_starts_with_the_log_as_it_is():
    log = Log("p")
    await committed(log, b"a")
    changes = log.changes()
    assert (await anext(changes)).messages == (Message(0, b"a"),)
    await changes.aclose()


async def test_changes_waits_while_nothing_changes():
    changes = Log("p").changes()
    await anext(changes)
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.05):
            await anext(changes)
    await changes.aclose()


async def test_changes_comes_with_an_uncommitted_write():
    log = Log("p")
    async with log.claim(Request(0)) as writer:
        changes = log.changes()
        await anext(changes)
        asyncio.get_running_loop().call_later(0.05, writer.append, b"a")
        async with asyncio.timeout(5):
            assert (await anext(changes)).messages == (Message(0, b"a"),)
        await changes.aclose()


async def test_changes_does_not_miss_what_happened_between_two_snapshots():
    log = Log("p")
    changes = log.changes()
    await anext(changes)
    await committed(log, b"a")
    async with asyncio.timeout(5):
        assert (await anext(changes)).messages == (Message(0, b"a"),)
    await changes.aclose()


async def test_changes_comes_when_the_holder_dies(spawn):
    log = Log("p")
    child = spawn(HOLD)
    changes = log.changes()
    assert (await anext(changes)).uncommitted
    child.kill()
    async with asyncio.timeout(5):
        while (await anext(changes)).uncommitted:
            pass
    await changes.aclose()


async def test_a_dead_holder_frees_the_log(spawn):
    log = Log("p")
    child = spawn(HOLD)
    asyncio.get_running_loop().call_later(0.05, child.kill)
    async with log.claim(Request(0), timeout=5) as writer:
        assert writer.append(b"mine") == 0


def silent_holder(log: Log, *writes: bytes):
    """A holder whose lock goes with no file event after it: the kernel's order when a process dies, made certain."""
    key = "000000000001.silent"
    (log.dir / f"held.{key}").write_text(json.dumps({"priority": 0, "data": "silent"}))
    journal = b"".join(RECORD.pack(b"S", id, len(write)) + write for id, write in enumerate(writes))
    (log.dir / f"journal.{key}").write_bytes(RECORD.pack(b"B", 0, 0) + journal)
    lock = open(log.dir / f"held.{key}", "rb")
    fcntl.flock(lock, fcntl.LOCK_EX)
    return lock


async def test_a_waiter_gets_the_log_when_the_holders_lock_goes_with_no_event():
    log = Log("p")
    lock = silent_holder(log)
    assert log.holder() == Request(0, "silent")
    claiming = asyncio.create_task(log.claim(Request(0)))
    await asyncio.sleep(0.05)
    assert not claiming.done()
    lock.close()
    async with asyncio.timeout(5):
        (await claiming).release()


async def test_changes_drops_a_dead_holders_writes_when_its_lock_goes_with_no_event():
    log = Log("p")
    lock = silent_holder(log, b"lost")
    changes = log.changes()
    assert (await anext(changes)).uncommitted == (Message(0, b"lost"),)
    lock.close()
    async with asyncio.timeout(5):
        assert (await anext(changes)).messages == ()
    await changes.aclose()


async def test_claim_waits_until_the_holder_releases():
    log = Log("p")
    holder = await log.claim(Request(0))
    waiter = asyncio.create_task(log.claim(Request(0)))
    await asyncio.sleep(0.1)
    assert not waiter.done()
    holder.release()
    async with asyncio.timeout(5):
        (await waiter).release()


async def test_claim_gives_up_after_its_timeout_and_leaves_the_queue():
    log = Log("p")
    async with log.claim(Request(0)):
        for timeout in (0, 0.05):
            with pytest.raises(TimeoutError):
                await log.claim(Request(9), timeout=timeout)
                pytest.fail(f"claimed a held log with timeout {timeout}")
            assert log.queue() == [Request(0)], f"timeout {timeout}"


async def test_a_claim_with_no_time_to_wait_takes_a_free_log():
    log = Log("p")
    async with log.claim(Request(0), timeout=0) as writer:
        assert log.holder() == Request(0)
        assert writer.append(b"a") == 0


async def test_a_cancelled_claim_leaves_the_queue(wait_until):
    log = Log("p")
    async with log.claim(Request(0)):
        waiter = asyncio.create_task(log.claim(Request(1)))
        await wait_until(log, lambda: len(log.queue()) == 2)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert log.queue() == [Request(0)]


async def test_the_log_goes_by_priority_then_by_arrival(wait_until):
    log = Log("p")
    holder = await log.claim(Request(0, "holder"))
    order = []

    async def take(label: str, priority: int) -> None:
        async with log.claim(Request(priority, label)):
            order.append(label)

    waiters = []
    for label, priority in [("low", 0), ("high", 1), ("high, later", 1), ("highest", 2)]:
        waiters.append(asyncio.create_task(take(label, priority)))
        await wait_until(log, lambda: len(log.queue()) == len(waiters) + 1)

    expected = ["highest", "high", "high, later", "low"]
    assert [request.data for request in log.queue()] == ["holder", *expected]
    holder.release()
    async with asyncio.timeout(5):
        await asyncio.gather(*waiters)
    assert order == expected


async def test_a_waiter_that_dies_leaves_the_queue(spawn, wait_until):
    log = Log("p")
    async with log.claim(Request(0)):
        child = spawn('print("ready", flush=True)\nimport asyncio\nfrom llvim.core.log import Log, Request\nasyncio.run(Log("p").claim(Request(5)))')
        await wait_until(log, lambda: len(log.queue()) == 2)
        child.kill()
        child.wait()
        assert log.queue() == [Request(0)]


async def test_queue_is_empty_when_no_one_holds_the_log():
    log = Log("p")
    (await log.claim(Request(0))).release()
    assert log.queue() == []


async def test_holder_is_the_request_of_whoever_holds_the_log(wait_until):
    log = Log("p")
    assert log.holder() is None
    async with log.claim(Request(1, "holder")):
        waiter = asyncio.create_task(log.claim(Request(5, "waiter")))
        await wait_until(log, lambda: len(log.queue()) == 2)
        assert log.holder() == Request(1, "holder")
    async with asyncio.timeout(5):
        (await waiter).release()
    assert log.holder() is None


async def test_a_fork_starts_at_the_head_and_goes_its_own_way():
    log = Log("p")
    await committed(log, b"a")
    fork = await log.fork("side")
    await committed(fork, b"b")
    assert messages(log) == [Message(0, b"a")]
    assert messages(fork) == [Message(0, b"a"), Message(1, b"b")]


async def test_a_fork_can_start_at_an_older_commit():
    log = Log("p")
    first = await committed(log, b"a")
    await committed(log, b"b")
    assert messages(await log.fork("side", first)) == [Message(0, b"a")]


async def test_fork_fails_if_the_name_exists():
    log = Log("p")
    await committed(log, b"a")
    await log.fork("side")
    with pytest.raises(FileExistsError):
        await log.fork("side")


async def test_an_empty_log_cannot_be_forked():
    with pytest.raises(ValueError):
        await Log("p").fork("side")


def test_bad_names_are_refused():
    for project, name in [("/", "main"), ("p", "a..b"), ("p", "x.lock"), ("p", "")]:
        with pytest.raises(ValueError):
            Log(project, name)
            pytest.fail(f"accepted project {project!r}, log {name!r}")


def test_a_project_is_kept_in_the_store_under_its_whole_path_in_one_folder(store):
    for project, folder in [
        ("/home/stoler/Documents/a", "home-stoler-Documents-a"),
        ("/a-b/c", "a%2Db-c"),
        ("/a/b-c", "a-b%2Dc"),
        ("/50%/x", "50%25-x"),
        ("/a/%2D", "a-%252D"),
    ]:
        assert Log(project).repo == store / folder, project


def test_a_project_relative_path_is_taken_from_the_working_folder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert Log("p").project == tmp_path / "p"
    assert Log("p").repo == Log(tmp_path / "p").repo


async def test_a_log_can_be_kept_in_any_folder(tmp_path):
    await committed(Log("p", repo=tmp_path / "elsewhere"), b"a")
    assert messages(Log("p", repo=tmp_path / "elsewhere")) == [Message(0, b"a")]
    assert messages(Log("p")) == []


async def test_logs_of_a_project_are_branches_of_one_repo():
    session = Log("p", "session")
    await committed(Log("p"), b"main")
    assert session.repo == Log("p").repo
    assert messages(session) == []


def git_paths(log: Log, commit: str) -> list[str]:
    listing = subprocess.run(["git", "--git-dir", str(log.repo), "ls-tree", "-r", "--name-only", commit], capture_output=True, text=True)
    return listing.stdout.split()


def git_object(log: Log, name: str) -> str:
    return subprocess.run(["git", "--git-dir", str(log.repo), "rev-parse", name], capture_output=True, text=True).stdout.strip()


async def test_messages_are_stored_in_buckets_of_n():
    log = Log("p", bucket=2)
    commit = await committed(log, *[b"x"] * 5)
    assert git_paths(log, commit) == ["messages/0/0", "messages/0/1", "messages/2/2", "messages/2/3", "messages/4/4", "next"]


async def test_a_commit_rewrites_only_the_buckets_it_changes():
    log = Log("p", bucket=2)
    before = await committed(log, *[b"x"] * 6)
    async with log.claim(Request(0)) as writer:
        writer.extend(0, b"y")
        after = await writer.commit()
    for bucket, same in [("0", False), ("2", True), ("4", True)]:
        assert (git_object(log, f"{before}:messages/{bucket}") == git_object(log, f"{after}:messages/{bucket}")) is same, bucket


async def test_a_new_bucket_size_leaves_old_messages_where_they_are():
    await committed(Log("p", bucket=2), *[b"x"] * 4)
    log = Log("p", bucket=3)
    async with log.claim(Request(0)) as writer:
        writer.replace(1, b"y")
        writer.remove(2)
        writer.append(b"z")
        commit = await writer.commit()
    assert git_paths(log, commit) == ["messages/0/0", "messages/0/1", "messages/2/3", "messages/3/4", "next"]
    assert messages(log) == [Message(0, b"x"), Message(1, b"y"), Message(3, b"x"), Message(4, b"z")]


async def test_a_long_lived_log_reads_the_same_as_a_fresh_one():
    rng = random.Random(3)
    log = Log("p", bucket=3)
    async with log.claim(Request(0)) as writer:
        commits = [await writer.commit()]
        for step in range(80):
            ids = [message.id for message in log.read().messages]
            choice = rng.choice(["append", "append", "extend", "replace", "remove", "restore", "commit"])
            if choice == "append" or not ids:
                writer.append(bytes([rng.randrange(256)]))
            elif choice == "extend":
                writer.extend(rng.choice(ids), b"+")
            elif choice == "replace":
                writer.replace(rng.choice(ids), b"")
            elif choice == "remove":
                writer.remove(rng.choice(ids))
            elif choice == "restore":
                writer.restore(rng.choice(commits))
            else:
                commits.append(await writer.commit())
            fresh = Log("p")
            assert log.read() == fresh.read(), f"step {step}, after {choice}"
            assert log.read(commits[-1]) == fresh.read(commits[-1]), f"step {step}, after {choice}"


def git_count(log: Log) -> dict[str, int]:
    out = subprocess.run(["git", "--git-dir", str(log.repo), "count-objects", "-v"], capture_output=True, text=True).stdout
    return {key: int(value) for key, value in (line.split(": ") for line in out.splitlines()) if value.isdigit()}


async def settled(log: Log, tidy) -> None:
    deadline = time.monotonic() + 5
    while not tidy(git_count(log)):
        assert time.monotonic() < deadline, f"never tidied: {git_count(log)}"
        await asyncio.sleep(0.01)


async def test_packs_and_loose_objects_are_merged_in_the_background_as_commits_add_them(monkeypatch):
    monkeypatch.setattr(log_module, "PACKS", 4)
    monkeypatch.setattr(log_module, "LOOSE", -1)
    for name, contents, tidy in [
        ("small commits, which leave loose objects", [b"x"], lambda count: count["count"] < 100),
        ("large commits, which leave a pack each", [b"y"] * 120, lambda count: count["packs"] <= 4),
    ]:
        log = Log("p", name.split(",")[0].replace(" ", "-"))
        async with log.claim(Request(0)) as writer:
            for _ in range(30):
                for content in contents:
                    writer.append(content)
                await writer.commit()
        await settled(log, tidy)
        assert len(Log("p", log.name).read().messages) == 30 * len(contents), name


async def test_the_users_git_settings_and_environment_do_not_reach_the_log(tmp_path, monkeypatch):
    marker = tmp_path / "a hook ran"
    hooks = tmp_path / "hooks"
    (hooks / "hooks").mkdir(parents=True)
    for folder in (hooks, hooks / "hooks"):
        hook = folder / "reference-transaction"
        hook.write_text(f"#!/bin/sh\ntouch '{marker}'\nexit 1\n")
        hook.chmod(0o755)
    settings = tmp_path / "gitconfig"
    settings.write_text(f"[core]\n\thooksPath = {hooks}\n[init]\n\ttemplateDir = {hooks}\n[commit]\n\tgpgSign = true\n")
    for variable, value in [("GIT_CONFIG_GLOBAL", str(settings)), ("GIT_DIR", str(tmp_path / "nowhere")), ("GIT_NAMESPACE", "elsewhere")]:
        monkeypatch.setenv(variable, value)
    log = Log("p")
    commit = await committed(log, b"a")
    assert log.head() == commit
    assert messages(Log("p")) == [Message(0, b"a")]
    assert not marker.exists()
    assert not (log.repo / "hooks" / "reference-transaction").exists()


async def test_a_fork_git_refuses_for_another_reason_does_not_say_the_name_is_taken():
    log = Log("p")
    await committed(log, b"a")
    (log.repo / "refs" / "heads" / "side.lock").write_text("")
    with pytest.raises(RuntimeError, match="side.lock"):
        await log.fork("side")
