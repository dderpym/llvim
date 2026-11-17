# `std/tools/bash/command.py`: COMMAND

`/bash [command]` in the input bar opens a terminal in the log: a shell, or the command. It is a bash call written by you instead of
the model, so the runner starts it, the viewer shows it as the usual live [box](box.md), and its output is the result when it exits.

```python
Input(commands=[*STANDARD, bash.COMMAND]).run()
```

- `/bash htop`: a call `{"command": "htop", "interactive": true}` with `user=True` and a new `call_id`, and a `tools` cue. Then the
  focus moves to the viewer.
- `/bash`: the same, for `bash`: a shell.
- Leave the terminal with ctrl-], or by exiting the program.

## Using it

- It is queued like a message ([bar.md](../../panels/input/bar.md)): typed while the model works, it goes in when the turn is over.
- The model does not reply to it, and speaking does not drop it ([calls.md](../calls.md)). The model sees what you ran, and what it
  printed, as a message of yours in its next turn.
- Ctrl-C in the bar stops it, as it stops any tool.

## Why it is this way

- **A call, not a terminal of its own.** The runner, the box and the result already do everything a terminal in the log needs. The
  only new things are that the call is the user's and that it takes the keyboard.
- **The focus moves after the commit.** Moved earlier, while the command waits in the queue, your typing would go to a viewer with
  nothing to type into.
