# `core/queue.py`: Request, Queue, Wake

The claims on one log, as files in its folder, each locked by the process it belongs to. `Wake` waits for the queue to move, including when a holder dies.

```python
queue = Queue(log_dir)
key, ticket = queue.join(Request(priority=1, data="me"))   # alive while `ticket` is open
wake = Wake(queue, Watch(log_dir, prefixes=("ticket.", "held.")))
while queue.take_turn(key) is None:
    await wake.changed()
...
queue.leave(key)
```

- `Request(priority, data=None)`: what a claimant tells the queue. Higher priority goes first.
- `join(request)`: a new ticket and its open file. Closing the file, or the process dying, ends the claim.
- `take_turn(key)`: makes `key` the holder and returns its request, or `None` if someone holds the log or another waiter is first. Deletes dead claims first.
- `held()`: the holder's key and request, or `None`. `live()`: the holder, and the waiters in the order they will get the log.
- `leave(key)`: deletes the claim's files, its journal included.
- `Wake(queue, watch).changed()`, async: returns on the watch's next event, or when the holder's lock goes. Cancelled, it stops
  reading the watch before it ends, so the watch can be closed right after.

## Using it

- `Request.data` must be JSON-serializable: other processes read it.
- While the log is held, each `Wake` keeps one thread blocked on the holder's lock. It is a daemon thread, so a program can exit while the holder lives on, and it ends when the holder lets go.
- Make the `Wake` before the first read, so a holder that dies between that read and the next wait is noticed as a change.

## Why it is this way

- **Claims are files with a lock in them.** Each claimant puts a file `ticket.<arrival>.<random>` in the log's folder and holds an `flock` on it while it lives. The holder renames its ticket to `held.…`. The kernel releases the lock when the process dies, however it dies. So a dead holder or waiter is noticed by anyone who tries the lock, without timeouts or heartbeats. A file whose lock can be taken is dead, and the next turn deletes it. A pid file was rejected: pids get reused.
- **A ticket is complete before it shows up.** It is written and locked as `new.…`, then renamed into place. A reader never sees a ticket with no request in it, and never sees one that is unlocked but alive.
- **One short mutex decides who is next.** A turn takes the mutex, deletes the dead claims, and takes the log only if there is no live holder and this ticket is first. Without it, two claimants who saw different queues could both take the log. The mutex file is opened read-only, so taking it makes no close-write event to wake the watchers.
- **The queue is ordered by priority, then arrival.** Arrival is a counter one higher than any ticket in the folder, so it needs no clock. The holder is never preempted: `Writer.outranked` tells it someone higher is waiting, `Writer.outranked_changed` when to look again, and yielding is its choice.
- **A priority is one int.** Every claimant's priority is compared with every other's, so they must all be of one comparable type. An int is enough: a ranking of several criteria can be folded into one number. It is held by the type only, not checked at runtime.
- **A holder's death is waited on with its lock, not only with file events.** A process that dies closes its ticket, which it had open for writing, and that close is an event ([watch.md](watch.md)). But the kernel sends it before it lets go of the dying process's locks, so a waiter woken by it can still find the holder alive, and no event follows. So `Wake` also keeps a thread blocked on a shared lock of the holder's file. The kernel wakes the thread exactly when the lock goes, however the holder died.
- **Queue knows a folder, not a log.** It needs nothing from git or the journal except the journal's name, to delete it with the claim. So it is tested on a bare temporary folder.
