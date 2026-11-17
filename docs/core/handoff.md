# `core/handoff.py`: Offer, take

A claim handed from the process that holds a log to one it chose. The log stays held the whole time: nobody waiting gets it in
between.

```python
# the holder
offer = writer.offer()
start_the_other_program(offer.address)        # in its arguments, its environment, or however it is told
await offer.taken(timeout=10)                 # from here on, `writer` is released

# the other process
writer = await log.adopt(address)             # a Writer on the same claim
```

A caller uses `Writer.offer` ([writer.md](writer.md)) and `Log.adopt` ([log.md](log.md)); this file is what they are made of.

- `Offer(key, ticket, let_go)`: listens for a taker. `address` is where: the path of a unix socket in a private folder in `/tmp`.
  - `taken(timeout=None)`, async: returns once a process has adopted the claim, after calling `let_go`. `TimeoutError` after
    `timeout` seconds, with the claim still the giver's. Either way the offer is closed.
  - `close()`: withdraws the offer. A taker that connected and was not answered gets `ConnectionError`.
- `take(address)`: the other end. The claim's key and its locked file, once the giver has let go. `ConnectionError` if nobody
  offers there or the offer was withdrawn. It blocks until the giver answers.

## Using it

- The giver chooses the taker by choosing who is given the address. Only a process running as the same user can reach it.
- Close an offer you do not await (`offer.close()`), or its folder in `/tmp` stays.
- What the giver had not committed is discarded, as on a release.
- If the taker dies after adopting, the claim dies with it and the log comes free. If the giver dies after the hand-over, nothing
  happens: the claim is no longer its.
- Works on one machine only, and needs unix sockets that carry file descriptors.

## Why it is this way

- **The claim's lock is on its open file, so the file is what is handed over.** A claim is alive while some process holds the
  `flock` of its file ([queue.md](queue.md)), and an `flock` belongs to the open file, not to the process that opened it. Sent
  to another process over a unix socket, the same open file is held by both, and the lock lasts until the last of them closes
  it. So the queue sees one holder from start to end, and no waiter is woken. Releasing and claiming again was rejected: whoever
  is first in the queue would get the log in between.
- **An address, not a pid.** A file descriptor can only be passed over a socket or to a child, and the taker is often neither
  the giver's child nor known by pid: a popup is started by tmux. The address works for both: a child is given it in its
  arguments, and any other process by whatever told it to start.
- **The socket is in `/tmp`, not in the log's folder.** A unix socket's path holds 107 bytes, and a log's folder under the store
  is often longer. The folder is made for the offer and readable only by its user.
- **The taker says it has the file, and the giver answers.** The giver lets go and answers in one step, with nothing awaited
  between, so its timeout cannot fall between the two. Without the answer, a giver that timed out just as the taker confirmed
  would leave both sure they held the log. A taker that is not answered closes its copy, and the claim is the giver's as before.
- **Handing over ends the giver's Writer the way a release does**, without leaving the queue. Its uncommitted writes are dropped
  and its journal is closed. The taker builds a fresh Writer on the head, which starts a fresh journal.
