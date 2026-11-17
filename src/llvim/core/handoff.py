"""core/handoff.py: Offer, a claim on its way from the process that holds it to one it chose, and take, the other end."""

import asyncio
import os
import shutil
import socket
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import IO

TAKEN = b"k"  # the taker says it has the file, and the giver answers that the claim is the taker's now


class Offer:
    """A claim offered to whoever is given `address`. The lock of a claim is on its open file, so the file handed to
    another process keeps the claim alive there."""

    def __init__(self, key: str, ticket: IO[bytes], let_go: Callable[[], None]):
        self._key, self._ticket, self._let_go = key, ticket, let_go
        # A unix socket's path is at most 107 bytes, and a log's folder is often longer: a private folder in /tmp is not.
        self._dir = Path(tempfile.mkdtemp(prefix="llvim-offer-"))
        self.address = str(self._dir / "claim")
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(self.address)
        self._server.listen(1)
        self._server.setblocking(False)

    async def taken(self, timeout: float | None = None) -> None:
        """Return once a process has adopted the claim: the giver no longer holds the log. TimeoutError after `timeout`
        seconds, with the claim still the giver's. Either way the offer is closed."""
        loop = asyncio.get_running_loop()
        try:
            async with asyncio.timeout(timeout):
                while True:
                    taker, _ = await loop.sock_accept(self._server)
                    with taker:
                        socket.send_fds(taker, [self._key.encode()], [self._ticket.fileno()])
                        if await loop.sock_recv(taker, 1) == TAKEN:
                            # Nothing is awaited between hearing the taker and answering it, so a timeout cannot land
                            # in between and leave both sides sure the claim is theirs.
                            self._let_go()
                            taker.send(TAKEN)
                            return
        finally:
            self.close()

    def close(self) -> None:
        self._server.close()
        shutil.rmtree(self._dir, ignore_errors=True)


def take(address: str) -> tuple[str, IO[bytes]]:
    """The claim offered at `address`, once the giver has let it go: its key and its locked file. ConnectionError if nobody
    offers there, or the giver withdrew. It blocks until the giver answers."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as giver:
        try:
            giver.connect(address)
            key, fds, _, _ = socket.recv_fds(giver, 256, 1)
        except OSError as error:
            raise ConnectionError(f"no claim is offered at {address}: {error}") from None
        if not fds:
            raise ConnectionError(f"no claim is offered at {address}")
        ticket = os.fdopen(fds[0], "ab")
        try:
            giver.sendall(TAKEN)
            answered = giver.recv(1) == TAKEN
        except OSError:
            answered = False
        if not answered:
            ticket.close()  # the giver still holds the claim through its own copy of the file
            raise ConnectionError(f"the claim offered at {address} was withdrawn")
        return key.decode(), ticket
