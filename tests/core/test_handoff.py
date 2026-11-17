"""core/handoff.py: a claim handed from the process that holds it to one it chose, with the log held throughout."""

import asyncio
import os
import subprocess
import sys

import pytest

from llvim.core import Log, Message, Released, Request

ADOPT = (
    "import asyncio, sys, time\n"
    "from llvim.core import Log\n"
    "async def adopt():\n"
    "    w = await Log('p').adopt(sys.argv[1])\n"
    "    w.append(b'from the child'); await w.commit()\n"
    "    print('ready', flush=True)\n"
    "    time.sleep(60)\n"
    "asyncio.run(adopt())\n"
)


@pytest.fixture
def log():
    return Log("p")


def child(address: str) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-c", ADOPT, address], stdout=subprocess.PIPE, text=True)


def stop(process: subprocess.Popen) -> None:
    process.kill()
    process.wait()
    process.stdout.close()


async def free(log: Log) -> bool:
    try:
        (await log.claim(Request(0, "probe"), timeout=0)).release()
        return True
    except TimeoutError:
        return False


async def hand_over(giver, taker_log: Log):
    """Offer and adopt in one process, as two logs on the same folder would in two."""
    offer = giver.offer()
    _, taker = await asyncio.gather(offer.taken(timeout=5), taker_log.adopt(offer.address))
    return taker


async def test_the_taker_gets_a_writer_on_the_same_claim_and_the_giver_is_released(log):
    giver = await log.claim(Request(3, "the claim"))
    giver.append(b"kept")
    await giver.commit()
    taker = await hand_over(giver, Log("p"))
    assert log.holder() == Request(3, "the claim") and len(log.queue()) == 1
    taker.append(b"more")
    await taker.commit()
    assert [m.content for m in log.read().messages] == [b"kept", b"more"]
    with pytest.raises(Released):
        giver.append(b"too late")
    giver.release()  # nothing left to release: the claim is the taker's
    assert log.holder() == Request(3, "the claim")
    taker.release()
    assert log.holder() is None


async def test_the_log_is_never_free_while_the_claim_changes_hands(log):
    giver = await log.claim(Request(0))
    offer = giver.offer()
    adopting = asyncio.ensure_future(Log("p").adopt(offer.address))
    taking = asyncio.ensure_future(offer.taken(timeout=5))
    seen_free = False
    while not (adopting.done() and taking.done()):
        seen_free = seen_free or await free(log)
        await asyncio.sleep(0)
    taker = adopting.result()
    assert not seen_free and not await free(log)
    taker.release()
    assert await free(log)


async def test_what_the_giver_had_not_committed_is_discarded(log):
    giver = await log.claim(Request(0))
    giver.append(b"kept")
    await giver.commit()
    giver.append(b"lost")
    taker = await hand_over(giver, Log("p"))
    assert log.read().messages == (Message(0, b"kept"),) and log.read().uncommitted == ()
    taker.release()


async def test_an_offer_nobody_takes_times_out_and_the_giver_still_holds_the_log(log):
    giver = await log.claim(Request(0))
    offer = giver.offer()
    with pytest.raises(TimeoutError):
        await offer.taken(timeout=0.05)
    giver.append(b"still mine")
    await giver.commit()
    assert log.read().messages == (Message(0, b"still mine"),) and not os.path.exists(offer.address)
    with pytest.raises(ConnectionError):
        await Log("p").adopt(offer.address)
    giver.release()


async def test_a_taker_that_comes_after_the_giver_gave_up_is_refused_and_holds_nothing(log):
    giver = await log.claim(Request(0))
    offer = giver.offer()
    adopting = asyncio.ensure_future(Log("p").adopt(offer.address))  # it connects, and is never answered
    await asyncio.sleep(0.05)
    offer.close()
    with pytest.raises(ConnectionError):
        await asyncio.wait_for(adopting, 5)
    giver.append(b"mine")
    await giver.commit()
    giver.release()
    assert await free(log)


async def test_a_claim_on_another_log_is_not_adopted(log):
    giver = await log.claim(Request(0))
    offer = giver.offer()
    results = await asyncio.gather(offer.taken(timeout=5), Log("p", "other").adopt(offer.address), return_exceptions=True)
    assert isinstance(results[1], ValueError)


async def test_another_process_adopts_and_goes_on_holding_after_the_giver_has_gone(log):
    giver = await log.claim(Request(0, "handed on"))
    offer = giver.offer()
    process = child(offer.address)
    try:
        await offer.taken(timeout=10)
        del giver, offer  # as if the giving process had ended
        assert process.stdout.readline().strip() == "ready"
        assert log.read().messages == (Message(0, b"from the child"),)
        assert log.holder() == Request(0, "handed on") and not await free(log)
    finally:
        stop(process)


async def test_when_the_process_that_adopted_dies_the_log_comes_free(log, wait_until):
    giver = await log.claim(Request(0))
    offer = giver.offer()
    process = child(offer.address)
    try:
        await offer.taken(timeout=10)
        assert process.stdout.readline().strip() == "ready"
    finally:
        stop(process)
    await wait_until(log, lambda: log.holder() is None)
    assert await free(log)


async def test_offering_needs_the_log_held(log):
    giver = await log.claim(Request(0))
    giver.release()
    with pytest.raises(Released):
        giver.offer()
