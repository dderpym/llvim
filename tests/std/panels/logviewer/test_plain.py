"""std/panels/logviewer/plain.py: the printer prints what is new, and clears and prints again what it cannot extend."""

import asyncio

from llvim.core import Request
from llvim.std.conversation import encode
from llvim.std.panels.logviewer.plain import Printer, follow
from llvim.std.panels.logviewer.text import CLEAR


async def test_what_is_new_is_printed_after_what_is_there_and_committing_it_prints_nothing_again(fake_log):
    printer = Printer()
    assert printer.update(fake_log.read()) == ""
    fake_log.say(["note"], "zero")
    printer.update(fake_log.read())
    async with await fake_log.claim(Request(0)) as writer:
        writer.append(encode(["note"], "one"))
        writer.append(encode(["note"], "two"))
        out = printer.update(fake_log.read())
        assert "one" in out and "two" in out and "zero" not in out and CLEAR not in out
        await writer.commit()
        assert printer.update(fake_log.read()).strip() == ""


async def test_a_streaming_message_prints_only_its_new_text_then_closes_with_a_line_break(fake_log):
    printer = Printer()
    async with await fake_log.claim(Request(0)) as writer:
        reply = writer.append(encode(["assistant"], "hel"))
        assert printer.update(fake_log.read()).endswith("hel")
        writer.extend(reply, b"lo")
        assert printer.update(fake_log.read()) == "lo"
        await writer.commit()
    out = printer.update(fake_log.read())
    assert out == "\n\n"  # finished: the line is closed, and nothing is printed again


async def test_what_it_cannot_extend_is_cleared_and_printed_again(fake_log):
    printer = Printer()
    fake_log.say(["note"], "a")
    fake_log.say(["note"], "b")
    printer.update(fake_log.read())
    async with await fake_log.claim(Request(0)) as writer:
        writer.remove(0)
        out = printer.update(fake_log.read())
    assert out.startswith(CLEAR) and "b" in out and "\na\n" not in out


async def test_once_prints_the_log_and_returns(fake_log, capsys):
    fake_log.say(["note"], "hello")
    await follow(fake_log, once=True)
    assert "hello" in capsys.readouterr().out


async def test_following_prints_each_change_until_cancelled(fake_log, capsys):
    following = asyncio.create_task(follow(fake_log))
    await asyncio.sleep(0.01)
    fake_log.say(["note"], "later")
    await asyncio.sleep(0.01)
    following.cancel()
    await asyncio.gather(following, return_exceptions=True)
    assert "later" in capsys.readouterr().out
