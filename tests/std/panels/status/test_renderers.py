"""std/panels/status/renderers.py: what is happening to the log in one phrase, and the model at it."""

from llvim.core import Message, Request, Snapshot
from llvim.std.conversation import decode, encode
from llvim.std.panels.logviewer.ansi import strip
from llvim.std.panels.status.bar import State
from llvim.std.panels.status.renderers import activity, model


def state(last=None, holder=None, uncommitted=False, busy_since=None, now=10.0, model=None):
    message = Message(0, encode(*last)) if last else None
    entry = decode(message, uncommitted, uncommitted) if message else None
    return State(Snapshot(None, (message,) if message else ()), entry, holder, model, busy_since, now)


PROVIDER = Request(0, {"provider": "openai", "model": "gpt"})

CASES = [
    (state(), "awaiting your input"),
    (state((["assistant"], "hi")), "awaiting your input"),
    (state((["cue", "generate"],)), "waiting for a model"),
    (state((["error"], "503 down\nmore")), "error: 503 down"),
    (state((["cue", "generate"],), PROVIDER), "waiting for the model"),
    (state((["thinking"], "hm"), PROVIDER, uncommitted=True), "thinking"),
    (state((["assistant"], "he"), PROVIDER, uncommitted=True), "writing"),
    (state((["status"], "attempting to reconnect in 2s"), PROVIDER, uncommitted=True), "attempting to reconnect in 2s"),
    (state((["user"], "hi"), Request(0, {"input": "me"})), "sending"),
    (state(holder=Request(0, "a script")), "busy: a script"),
]


def test_activity_says_what_is_happening_in_one_phrase():
    for given, phrase in CASES:
        assert strip(activity(given)) == phrase, phrase


def test_while_the_turn_runs_activity_says_for_how_long_in_whole_seconds():
    assert strip(activity(state((["cue", "generate"],), busy_since=2.5, now=14.9))) == "waiting for a model · 12s"


def test_the_model_is_the_one_at_work_else_the_one_that_wrote_last_else_none():
    assert strip(model(state(holder=PROVIDER, model="old"))) == "gpt"
    assert strip(model(state(model="old"))) == "old"
    assert model(state()) is None
