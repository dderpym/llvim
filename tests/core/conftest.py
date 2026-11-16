import asyncio
import subprocess
import sys
from collections.abc import Callable

import pytest


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    """A fresh, empty store for each test, so no test touches the real one."""
    monkeypatch.setenv("LLVIM_STORE", str(tmp_path / "store"))
    return tmp_path / "store"


@pytest.fixture
def spawn():
    """Run python code in a child process; returns once it prints "ready". Killed at the end, never released."""
    children = []

    def run(code: str) -> subprocess.Popen:
        child = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
        children.append(child)
        assert child.stdout.readline().strip() == "ready"
        return child

    yield run
    for child in children:
        child.kill()
        child.wait()
        child.stdout.close()


async def until(log, condition: Callable[[], bool], seconds: float = 5) -> None:
    """Wait on the log's changes until `condition()` holds, failing after `seconds`."""
    async with asyncio.timeout(seconds):
        changes = log.changes()
        try:
            async for _ in changes:
                if condition():
                    return
        finally:
            await changes.aclose()


@pytest.fixture
def wait_until():
    """wait_until(log, condition): `until`, as a fixture, since conftest is not importable from a test."""
    return until
