# `core/watch.py`: Watch

Inotify on one folder, waited on from the event loop.

```python
watch = Watch(log_dir, prefixes=("ticket.", "held."))
await watch.changed()     # an event on a ticket or held file came since the last call
watch.close()
```

- `Watch(directory, prefixes=("",))`: watches `directory` for files written, created, renamed or deleted. Only events on names with one of `prefixes` count. Not on Linux: raises `NotImplementedError`.
- `changed()`, async: returns once a wanted event has come since the last call. Events that came before the call count.
- `close()`: closes the inotify instance. Closing twice does nothing.

## Using it

- Each `Watch` is one inotify instance until it is closed or garbage collected. The kernel limits how many a user may have (`fs.inotify.max_user_instances`).
- An overflow of the kernel's queue counts as a wanted event: something may have been missed, so the caller reads again.

## Why it is this way

- **Waiting is on kernel file events, never polling.** Every change to a log makes an event in its folder: a ticket or journal written, renamed or deleted, and the close of a ticket by a process that dies. Polling would cost either latency or CPU.
- **Readers make no events.** They open files read-only and do not write, so reading never wakes anyone, and two waiters cannot wake each other forever.
- **Prefixes, so a waiter ignores what it does not care about.** `claim` watches only tickets and holders, so a streaming holder does not wake every waiter on every chunk of its journal.
- **Inotify through `ctypes`, handed to the event loop with `add_reader`.** Portable stdlib watching does not exist. Linux only; kqueue support was left out until it can be tested.
