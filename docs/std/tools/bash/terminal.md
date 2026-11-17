# `std/tools/bash/terminal.py`: run

A command in a hidden tmux window. The window's pane is tagged with the tool call's id, so the [box](box.md) in the viewer can find
it and show it.

```python
ran = await run("make test", project, call_id="call_1", timeout=120, interactive=False)
ran.output, ran.status, ran.timed_out, ran.cancelled
```

- `run(command, cwd, call_id, timeout, interactive, tmux=None)`, async: a `Ran` once the command has exited or been stopped.
  - Not interactive: its stdout and stderr are appended to a temporary file (readable only by you), and `tail` shows the file in the
    pane. `output` is the file's bytes as text, and the file is removed.
  - Interactive: it runs on the terminal, and `output` is the screen and its history, without the empty rows under the last line.
  - It exits: `status` is its exit status.
  - Still running at `timeout`: it gets ctrl-c, then `GRACE` (3 s) to exit, then its terminal is closed. `timed_out`, `status` is `None`.
  - Cancelled: the same stop, then it returns, with `cancelled` set, rather than raising.
- `CALL_OPTION` (`@llvim_call`): the pane option that holds the call id.
- `control()`: the one tmux connection, made when first needed, and again if it has closed. Raises `TmuxError` outside tmux.

## Using it

- The command runs as `PAGER=cat GIT_PAGER=cat bash -c <command>`; not interactive, with `</dev/null >>file 2>&1`.
- The window is closed when `run` returns. A command that left something running in the background does not hold the call, even
  if that keeps writing: it writes to a file, not a pipe that must be closed.
- `tail --pid` is GNU coreutils'. Like the rest of llvim, this needs Linux.
- It looks at the terminal every 50 ms. Each look is one tmux command over the open connection, which takes well under a
  millisecond.

## Why it is this way

- **Bash owns its terminal, not the runner.** The runner only runs tools. A tool with no terminal costs nothing, and how a terminal
  is started, tagged and stopped lives next to the box that shows it, which shares `CALL_OPTION`.
- **Cancelled, it returns.** The call's result should be what the command printed before it was stopped. An asyncio cancel carries
  no value, so `run` takes it, stops the command, and returns what it had written. The tool turns that into an error result.
- **Ctrl-C first, then closing.** Ctrl-C lets a program clean up as it would in your shell. Closing the window ends one that
  ignores it.
- **A file, not a pipe.** `cmd | tee` would also keep the bytes and show them live, but a background job (`npm run dev &`) holds a
  pipe open, and the call would wait until its timeout. Running the command in the background with `tail` in front was also
  rejected: a shell with no job control makes its background jobs ignore ctrl-c, so a stop would not reach the command.
- **Tagged before it starts.** `Embedded.start` sets the option before the command runs, so the box never sees an untagged pane.
