# `std/tools/bash/shared.py`: start, type_keys, hand_to_user, close

A terminal kept open past the call that started it, which the model and the user take turns at. The model types and reads. When
something is the user's to type (a password, a passphrase, a choice), the model hands them the keyboard and waits until they hand
it back.

```python
seen = await shared.start("sudo apt upgrade", project, "call_1", timeout=120, settle=1.5)   # "[sudo] password for me: "
seen = await shared.hand_to_user("call_1", timeout=3600)        # the user types; ctrl-g in the box hands it back
seen = await shared.type_keys("call_1", "y\n", timeout=120, settle=1.5)
seen = await shared.close("call_1")
```

- `start(command, cwd, id, timeout, settle, tmux=None)`: runs `command` on a terminal (as [terminal.md](terminal.md) runs an
  interactive one) kept under `id`, and waits as `type_keys` does.
- `type_keys(id, keys, timeout, settle)`: types `keys` and returns once the screen has been still for `settle` seconds.
  - A newline is Enter: it is sent as a carriage return, as a keyboard sends it.
  - Empty keys: only waits and looks again.
  - Still changing at `timeout`: returns with `still_changing`, and the program keeps running.
  - It exits: `status`, `running` is false, and the terminal is closed.
- `hand_to_user(id, timeout)`: sets the pane's `OWNER` option to `USER` and returns when the box sets it back (`handed_back`),
  the program exits, or `timeout` runs out. Whichever it is, the terminal is the model's again.
- `close(id)`: ctrl-c, then the terminal is closed on it after `terminal.GRACE`, as a timed-out command is stopped. `status` is
  `None` if it had to be closed on.
- Cancelled: `start`, `type_keys` and `hand_to_user` return with `cancelled` set, and the program keeps running.
- `Closed`: no terminal is kept under that id, or tmux failed on it (its pane was killed). A terminal tmux failed on is forgotten.
- `close_all()`: closes them all. It runs at exit.
- `OWNER` (`@llvim_owner`), `AGENT`, `USER`: the pane option that says who may type.

## Using it

- Each `Seen.output` starts at the row the cursor was on at the last look. A shell's turn reads
  `$ echo 42`, `42`, `$ `: the line typed on, what it printed, and the prompt it is at. A program on the alternate screen (vim,
  top, less) gives its whole screen each time.
- A terminal is kept by the process that started it, in memory. The runner is that process. When it exits, its terminals are
  closed, so `llvim-tools --once` cannot leave one open for a later call.
- Nothing kills a kept terminal that is neither closed nor exits until its process exits. `timeout` limits a wait, not the
  program.
- One look costs one or two tmux commands every 50 ms while it waits. Each takes well under a millisecond.

## Why it is this way

- **The keyboard has one owner at a time.** The model's keys and the user's keys in one prompt at once would be a password with a
  `y` in the middle. While the user has it, the box takes keys and the model's call is waiting. While the model has it, the box
  does not take the keyboard.
- **The owner lives in a tmux pane option.** The runner and the viewer are different processes that already agree on the pane by
  its `@llvim_call` tag. A second option is all they need to agree on who types. Nothing goes in the log.
- **Handing back is a key, not a guess.** Spotting a prompt on the screen to decide the user is done is fragile. If it guessed
  wrong, the model would type into the user's password prompt. The user says when they are done.
- **The user's turn has a time limit, and the model's wait has one too.** A forgotten handoff ends at `user_timeout` and the
  terminal is the model's again. Every call returns, and none of them waits forever on a program or a person.
- **Settled, not finished.** A program that asks a question does not exit, so waiting for it to exit would wait for the timeout.
  A screen still for a moment is the point where a person would read it. A program that pauses longer than that is looked at
  again with an empty `type_keys`.
- **From the cursor's row, not the whole screen.** Giving the screen each time repeated up to a screenful of old lines on every
  turn. A line program writes below its cursor, so the rows above it are final. A full-screen program does not, so it gets the
  whole screen.
- **The model sees what the user typed only as the program echoed it.** `sudo` and `ssh` do not echo a password. What the user
  did is in the output after they hand back, as it would be on their own screen.
