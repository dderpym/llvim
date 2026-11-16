"""core/watch.py: Watch, inotify on one folder, waited on from the event loop."""

import asyncio
import ctypes
import os
import struct
import sys
import weakref
from pathlib import Path

_IN_MODIFY, _IN_CLOSE_WRITE, _IN_MOVED_FROM, _IN_MOVED_TO, _IN_CREATE, _IN_DELETE = 0x2, 0x8, 0x40, 0x80, 0x100, 0x200
_IN_Q_OVERFLOW = 0x4000
_EVENTS = _IN_MODIFY | _IN_CLOSE_WRITE | _IN_MOVED_FROM | _IN_MOVED_TO | _IN_CREATE | _IN_DELETE
_EVENT = struct.Struct("iIII")  # wd, mask, cookie, name length
_libc = ctypes.CDLL(None, use_errno=True) if sys.platform == "linux" else None


class Watch:
    """Inotify on one directory, wanting only events on names with one of `prefixes`."""

    def __init__(self, directory: Path, prefixes: tuple[str, ...] = ("",)):
        if _libc is None:
            raise NotImplementedError("llvim waits with inotify, which only Linux has")
        fd = _libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
        if fd < 0:
            raise OSError(ctypes.get_errno(), "inotify_init1")
        self._fd, self._prefixes = fd, prefixes
        self.close = weakref.finalize(self, os.close, fd)
        if _libc.inotify_add_watch(fd, os.fsencode(directory), _EVENTS) < 0:
            errno = ctypes.get_errno()
            self.close()
            raise OSError(errno, "inotify_add_watch", str(directory))

    async def changed(self) -> None:
        """Return once a wanted event has come since the last call."""
        loop = asyncio.get_running_loop()
        while not self._drain():
            readable = loop.create_future()
            loop.add_reader(self._fd, settle, readable)
            try:
                await readable
            finally:
                loop.remove_reader(self._fd)

    def _drain(self) -> bool:
        wanted = False
        while True:
            try:
                data = os.read(self._fd, 65536)
            except BlockingIOError:
                return wanted
            at = 0
            while at < len(data):
                _, mask, _, size = _EVENT.unpack_from(data, at)
                name = os.fsdecode(data[at + _EVENT.size : at + _EVENT.size + size].rstrip(b"\0"))
                wanted = wanted or bool(mask & _IN_Q_OVERFLOW) or name.startswith(self._prefixes)
                at += _EVENT.size + size


def settle(future: asyncio.Future) -> None:
    """Done, unless it already is: a callback may come after the waiter gave up."""
    if not future.done():
        future.set_result(None)
