# `std/panels/input/bar.py`: Bar, send, stop

The input bar's state (the editor, the menu, a notice), what each key does to it, and sending what was typed.

```python
bar = Bar(log, screen, Panes(), Growth(), history, commands=STANDARD)
await bar.run()                                  # until /quit or the terminal closes
```

- `send(log, text)`, async: once the turn is over ([cues.md](../../cues.md)), commits a `["user"]` message with `text` and a
  `GENERATE` cue, as the user. If a cue was left while it waited for the log, it waits for that turn too.
- `stop(log)`, async: takes the log at `STOP_PRIORITY`, above any provider, and commits `["user", "stop"]` "User stopped this
  response.", with no cue.
- `quit_session()`: ends the tmux session the bar runs in, and every panel with it. Outside tmux, nothing.
- `Bar(log, screen, panes, growth, history=None, commands=(), send=send, quit=quit_session, stop=stop, busy=busy)`:
  - `on_key(raw)`, `on_mouse(event)`: what a key does (see [input.md](input.md)).
  - `draw()`: the rows, after asking `growth` for the height they need.
  - `run()`, async: reads the keyboard and draws, until a command or the terminal ends it. On leaving, what is still being sent or
    stopped is cancelled.

## Using it

- Enter clears the line at once. The message goes into the outbox, and the outbox sends one message at a time, in the order typed.
  If the model is busy, or something is already queued, the bar says "queued", and shows how many wait.
- A send that fails is reported under the prompt ("not sent: ..."); the next one still goes. The text is in the history.
- Ctrl-C while busy starts one `stop`; a second press while it runs does nothing more. The model hands over within a fraction of a
  second, even if its server is silent ([openai.md](../../providers/openai.md)). Queued messages go in once the stop is committed.
- A command may be `async`: the bar runs it beside the keyboard and reports what it raises.
- `send`, `stop`, `quit` and `busy` are parameters so a test, or a different session, can put its own in.

## Why it is this way

- **A message waits for the turn; only stop cuts it short.** A message claims at `PRIORITY`, 0, a provider's default, so a provider
  holding the log is never `outranked()` by it, even if it claims in the moment between the bar's look and its claim. Stopping is the
  one thing that should cut a reply short, so it alone claims above.
- **The stop is a user message.** It tells the model, in the next turn, why its last reply ends where it does. It has no cue: nothing
  should answer it.
- **Every message goes through the outbox.** Sending at once when the model is idle and queueing when it is busy were two paths that
  did the same thing, so there is one: wait for the turn, then claim. When the model is idle the wait is one read.
- **Work runs beside the keyboard.** Sending, stopping and an async command are tasks on the bar's loop, so typing never waits for the
  log. Each ends by waking the loop, which draws what changed.
