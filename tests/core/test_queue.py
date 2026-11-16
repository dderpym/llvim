"""core/queue.py: the claims on one log as locked files, and Wake, which waits for the queue to move."""

import asyncio
import fcntl
import json

import pytest

from llvim.core.queue import Queue, Request, Wake
from llvim.core.watch import Watch

JOIN = """
import time
from pathlib import Path
from llvim.core.queue import Queue, Request
ticket = Queue(Path({dir!r})).join(Request(5))
print("ready", flush=True)
time.sleep(60)
"""


@pytest.fixture
def queue(tmp_path):
    return Queue(tmp_path)


def test_waiters_are_ordered_by_priority_then_by_arrival(queue):
    tickets = [queue.join(Request(priority, label)) for label, priority in [("a", 0), ("b", 1), ("c", 1), ("d", 2)]]
    held, waiting = queue.live()
    assert held is None
    assert [request.data for _, request in waiting] == ["d", "b", "c", "a"]
    for _, ticket in tickets:
        ticket.close()


def test_only_the_first_waiter_takes_a_free_log(queue):
    (first, first_ticket), (second, second_ticket) = queue.join(Request(1, "first")), queue.join(Request(0))
    assert queue.take_turn(second) is None
    assert queue.take_turn(first) == Request(1, "first")
    assert queue.held() == (first, Request(1, "first"))
    assert queue.take_turn(second) is None
    first_ticket.close()
    second_ticket.close()


def test_a_closed_ticket_is_dead_and_the_next_turn_deletes_it(queue):
    dead, dead_ticket = queue.join(Request(9))
    alive, ticket = queue.join(Request(0))
    dead_ticket.close()
    assert queue.live() == (None, [(alive, Request(0))])
    assert queue.take_turn(alive) == Request(0)
    assert not list(queue.dir.glob(f"*.{dead}"))
    ticket.close()


async def test_a_waiter_in_a_process_that_dies_is_gone_from_the_queue(queue, spawn):
    child = spawn(JOIN.format(dir=str(queue.dir)))
    assert [request for _, request in queue.live()[1]] == [Request(5)]
    child.kill()
    child.wait()
    assert queue.live() == (None, [])


def test_leaving_deletes_the_claims_files(queue):
    key, ticket = queue.join(Request(0))
    queue.take_turn(key)
    (queue.dir / f"journal.{key}").write_bytes(b"")
    queue.leave(key)
    ticket.close()
    assert sorted(path.name for path in queue.dir.iterdir()) == ["mutex"]


async def test_wake_comes_when_someone_joins(queue):
    wake = Wake(queue, Watch(queue.dir))
    joining = asyncio.get_running_loop().run_in_executor(None, queue.join, Request(0))
    async with asyncio.timeout(5):
        await wake.changed()
    wake.close()
    (await joining)[1].close()


async def test_wake_comes_when_the_holders_lock_goes_with_no_event(queue):
    key = "000000000001.silent"
    (queue.dir / f"held.{key}").write_text(json.dumps({"priority": 0}))
    lock = open(queue.dir / f"held.{key}", "rb")
    fcntl.flock(lock, fcntl.LOCK_EX)
    wake = Wake(queue, Watch(queue.dir, prefixes=("nothing.",)))
    asyncio.get_running_loop().call_later(0.05, lock.close)
    async with asyncio.timeout(5):
        await wake.changed()
    assert queue.held() is None
    wake.close()
