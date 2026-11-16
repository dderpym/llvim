"""core/watch.py: inotify on one folder, waited on from the event loop."""

import asyncio

import pytest

from llvim.core.watch import Watch


async def test_changed_comes_after_an_event_on_a_wanted_name(tmp_path):
    watch = Watch(tmp_path, prefixes=("ticket.",))
    asyncio.get_running_loop().call_later(0.05, (tmp_path / "ticket.1").write_text, "")
    async with asyncio.timeout(5):
        await watch.changed()
    watch.close()


async def test_events_on_other_names_do_not_count(tmp_path):
    watch = Watch(tmp_path, prefixes=("ticket.",))
    (tmp_path / "journal.1").write_text("")
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.05):
            await watch.changed()
    watch.close()


async def test_an_event_before_the_call_counts(tmp_path):
    watch = Watch(tmp_path)
    (tmp_path / "x").write_text("")
    async with asyncio.timeout(5):
        await watch.changed()
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.05):
            await watch.changed()
    watch.close()
