"""std/void/command.py: /void shows the picker in a tmux popup. The popup itself needs a person's terminal, so only the command
it is given is tested here."""

import asyncio
import shlex

import pytest

from llvim.std.panels.input.commands import Context
from llvim.std.void import COMMAND
from llvim.std.void.command import popup, show
from llvim.std.void.picker import REQUEST


def test_it_is_the_command_void_for_an_input_bar_to_be_given():
    assert COMMAND.name == "void"


def test_the_popup_runs_the_picker_for_the_log_adopting_the_claim_and_closes_with_it(fake_log, monkeypatch):
    monkeypatch.setenv("LLVIM_STORE", "/the store")
    monkeypatch.setenv("PATH", "/bin")
    monkeypatch.delenv("LLVIM_HOME", raising=False)
    command = popup(fake_log, "/tmp/offer/claim")
    assert command[:3] == ["tmux", "display-popup", "-E"] and command[command.index("-d") + 1] == str(fake_log.project)
    picker = shlex.split(command[-1])
    assert picker == [
        "env", "PATH=/bin", "LLVIM_STORE=/the store", "llvim-void", "main", "-p", str(fake_log.project), "--adopt", "/tmp/offer/claim",
    ]  # fmt: skip


def test_the_popup_goes_to_the_client_it_is_told_and_else_to_tmuxs_choice(fake_log):
    assert "-c" not in popup(fake_log, "a")
    command = popup(fake_log, "a", "/dev/pts/3")
    assert command[command.index("-c") + 1] == "/dev/pts/3"


def test_outside_tmux_it_says_so_and_queues_nothing(fake_log):
    notices, queued = [], []
    COMMAND.run(Context(fake_log, notices.append, lambda: None, {}, None, lambda label, work: queued.append(label)), "")
    assert notices == ["/void opens in a tmux popup, and this is not in tmux"] and queued == []


def test_in_tmux_it_is_queued_like_a_message(fake_log, monkeypatch):
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/llvim,1,0")
    notices, queued = [], []
    COMMAND.run(Context(fake_log, notices.append, lambda: None, {}, None, lambda label, work: queued.append(label)), "")
    assert queued == ["/void"] and notices == []


class Popup:
    """The popup as the command sees it: a process that ends when `close` is called. `adopts`: the picker in it takes the
    claim offered to it, as the real one does."""

    def __init__(self, log, adopts=True, returncode=0, error=b""):
        self.log, self.adopts, self.returncode, self.error = log, adopts, returncode, error
        self.commands, self.closed, self.writer = [], asyncio.Event(), None

    async def start(self, *command, **kw):
        self.commands.append(command)
        if command[1] != "display-popup":
            return Listing()
        if self.adopts:
            self.writer = await self.log.adopt(shlex.split(command[-1])[-1])
        else:
            self.closed.set()
        return self

    async def communicate(self):
        await self.closed.wait()
        return b"", self.error

    def close(self):
        if self.writer:
            self.writer.release()
        self.closed.set()


class Listing:
    returncode = 0

    async def communicate(self):
        return b"0 /dev/pts/1\n", b""


@pytest.fixture
def popup_of(fake_log, monkeypatch):
    def make(**kw):
        shown = Popup(fake_log, **kw)
        monkeypatch.setattr(asyncio, "create_subprocess_exec", shown.start)
        return shown

    return make


async def test_it_claims_the_log_only_once_the_turn_in_progress_is_over_and_then_shows_the_popup(fake_log, popup_of):
    shown = popup_of()
    fake_log.ask("hi")  # a cue the model has not answered
    showing = asyncio.ensure_future(show(fake_log, lambda text: None))
    await asyncio.sleep(0.02)
    assert fake_log.claims == [] and not any(c[1] == "display-popup" for c in shown.commands)
    fake_log.say(["assistant"], "hello")
    while shown.writer is None:
        await asyncio.sleep(0.005)
    assert fake_log.claims == [REQUEST] and fake_log.holder() == REQUEST
    shown.close()
    await asyncio.wait_for(showing, 1)


async def test_the_claim_is_handed_to_the_picker_and_the_log_is_held_until_the_picker_lets_go(fake_log, popup_of):
    shown = popup_of()
    notices = []
    showing = asyncio.ensure_future(show(fake_log, notices.append))
    while shown.writer is None:
        await asyncio.sleep(0.005)
    await asyncio.sleep(0.02)
    assert fake_log.holder() == REQUEST and not showing.done()
    shown.writer.append(b"the picker writes with it")
    await shown.writer.commit()
    shown.close()
    await asyncio.wait_for(showing, 1)
    assert fake_log.holder() is None and notices == [] and fake_log.offers == {}
    assert shown.commands[-1][shown.commands[-1].index("-c") + 1] == "/dev/pts/1"


async def test_a_popup_that_ends_without_taking_the_claim_frees_the_log_and_says_why(fake_log, popup_of):
    popup_of(adopts=False, returncode=1, error=b"no client\n")
    notices = []
    await asyncio.wait_for(show(fake_log, notices.append), 1)
    assert notices == ["/void: no client"] and fake_log.holder() is None and fake_log.offers == {}
