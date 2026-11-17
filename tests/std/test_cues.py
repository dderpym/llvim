"""std/cues.py: a cue is a message, wanted while it is the last one; sending, receiving, and waiting for the turn."""

import asyncio

from llvim.core import Message, Request, Snapshot
from llvim.std.conversation import decode, encode, entries
from llvim.std.cues import GENERATE, busy, channel, cued, is_cue, receive, send, take, take_turn


def snapshot(*contents):
    return Snapshot("c", tuple(Message(i, c) for i, c in enumerate(contents)))


def entry(content):
    return decode(Message(0, content))


# --- checking ---


def test_a_cue_names_its_channel_and_other_messages_name_none():
    assert channel(entry(encode(["cue", GENERATE]))) == GENERATE
    for other in (encode(["user"], "hi"), encode(["cue"]), encode(["cue", 1]), encode(["cue", "a", "b"])):
        assert channel(entry(other)) is None and not is_cue(entry(other)), other


def test_is_cue_asks_about_any_cue_or_a_cue_on_one_channel():
    cue = entry(encode(["cue", "tools"]))
    assert is_cue(cue) and is_cue(cue, "tools") and not is_cue(cue, GENERATE)


def test_a_cue_is_wanted_while_it_is_the_last_message_and_whatever_follows_overtakes_it():
    assert cued(snapshot()) is None
    assert cued(snapshot(encode(["user"], "hi"), encode(["cue", GENERATE]))) == GENERATE
    assert cued(snapshot(encode(["cue", GENERATE]), encode(["assistant"], "hello"))) is None


def test_the_turn_is_busy_while_a_cue_waits_or_someone_holds_the_log(fake_log):
    assert not busy(fake_log)
    fake_log.ask()
    assert busy(fake_log)
    fake_log.say(["assistant"], "done")
    assert not busy(fake_log)
    fake_log.hold(Request(0))
    assert busy(fake_log)


# --- sending and receiving ---


async def test_a_cue_sent_goes_in_with_the_writers_next_commit(fake_log):
    async with await fake_log.claim(Request(0)) as writer:
        writer.append(encode(["user"], "hi"))
        send(writer, GENERATE)
        assert fake_log.head() is None
        await writer.commit()
    assert [e.tags for e in entries(fake_log.read())] == [["user"], ["cue", GENERATE]] and cued(fake_log.read()) == GENERATE


async def test_take_gives_the_log_only_while_its_channel_is_cued(fake_log):
    assert await take(fake_log, GENERATE, Request(0)) is None
    fake_log.say(["cue", "tools"])
    assert await take(fake_log, GENERATE, Request(0)) is None and fake_log.claims == []
    fake_log.ask()
    writer = await take(fake_log, GENERATE, Request(0))
    assert writer is not None and fake_log.holder() == Request(0)
    writer.release()


async def test_take_lets_go_if_the_cue_was_overtaken_while_it_waited_for_the_log(fake_log):
    fake_log.ask()
    fake_log.hold(Request(0, "someone"))
    taking = asyncio.create_task(take(fake_log, GENERATE, Request(0)))
    await asyncio.sleep(0.01)
    fake_log.say(["assistant"], "answered by someone else")
    fake_log.hold(None)
    assert await asyncio.wait_for(taking, 1) is None and fake_log.holder() is None


async def test_receive_gives_the_log_held_for_each_cue_and_releases_it_after(fake_log):
    got = []

    async def listen():
        async for writer in receive(fake_log, GENERATE, Request(0, "listener")):
            got.append(fake_log.holder())
            writer.append(encode(["assistant"], f"answer {len(got)}"))
            await writer.commit()

    listening = asyncio.create_task(listen())
    for _ in range(2):
        fake_log.ask()
        while cued(fake_log.read()) or fake_log.holder():
            await asyncio.sleep(0.001)
    listening.cancel()
    await asyncio.gather(listening, return_exceptions=True)
    assert got == [Request(0, "listener")] * 2 and fake_log.holder() is None
    assert [e.content for e in entries(fake_log.read()) if e.tags == ["assistant"]] == ["answer 1", "answer 2"]


# --- the turn ---


async def test_take_turn_waits_for_the_holder_and_for_every_cue_to_be_answered(fake_log):
    fake_log.ask()
    fake_log.hold(Request(0, "model"))
    taking = asyncio.create_task(take_turn(fake_log, Request(0, "me")))
    await asyncio.sleep(0.01)
    fake_log.say(["cue", "tools"])  # the model hands the turn to the runner
    fake_log.hold(None)
    await asyncio.sleep(0.01)
    assert not taking.done()  # nobody holds the log, but the turn is not over
    fake_log.say(["tool_result"], "ok")
    writer = await asyncio.wait_for(taking, 1)
    assert fake_log.holder() == Request(0, "me")
    writer.release()
