"""std/cues.py: a cue is a message, and it is wanted while it is the last one."""

from llvim.core import Message, Request, Snapshot
from llvim.std.conversation import decode, encode
from llvim.std.cues import GENERATE, busy, channel, cue, cued


def snapshot(*contents):
    return Snapshot("c", tuple(Message(i, c) for i, c in enumerate(contents)))


def test_a_cue_names_its_channel_and_other_messages_name_none():
    assert channel(decode(Message(0, cue(GENERATE)))) == GENERATE
    for other in (encode(["user"], "hi"), encode(["cue"]), encode(["cue", 1]), encode(["cue", "a", "b"])):
        assert channel(decode(Message(0, other))) is None, other


def test_a_cue_is_wanted_while_it_is_the_last_message_and_whatever_follows_overtakes_it():
    assert cued(snapshot()) is None
    assert cued(snapshot(encode(["user"], "hi"), cue(GENERATE))) == GENERATE
    assert cued(snapshot(cue(GENERATE), encode(["assistant"], "hello"))) is None


def test_the_turn_is_busy_while_a_cue_waits_or_someone_holds_the_log(fake_log):
    assert not busy(fake_log)
    fake_log.ask()
    assert busy(fake_log)
    fake_log.say(["assistant"], "done")
    assert not busy(fake_log)
    fake_log.hold(Request(0))
    assert busy(fake_log)
