# `std/panels/input/bar.py`: Bar, send, stop

The input bar's state (the editor, the menu, a notice), what each key does to it, and sending what was typed.

```python
bar = Bar(log, screen, Panes(), Growth(), history, commands=STANDARD)
await bar.run()                                  # until /quit or the terminal closes
```

- `after_turn(log, write, message="")`, async: takes the log once the whole turn is over (`cues.take_turn`,
  [cues.md](../../cues.md)), calls `write(writer)` and commits as the user.
- `send(log, text)`, async: `after_turn` writing a `["user"]` message with `text` and a `GENERATE` cue.
- `stop(log)`, async: takes the log at `STOP_PRIORITY`, above any provider, and commits `["user", "stop"]` "User stopped this
  response.", with no cue.
- `quit_session()`: ends the tmux session the bar runs in, and every panel with it. Outside tmux, nothing.
- `Bar(log, screen, panes, growth, history=None, commands=(), send=send, quit=quit_session, stop=stop, busy=busy)`:
  - `on_key(raw)`, `on_mouse(event)`: what a key does (see [input.md](input.md)).
  - `queue(label, work)`: runs `work(log)` after everything queued before it. A sent line is queued this way, and so is
    `/continue` ([generate.md](generate.md)), through `Context.queue`.
  - `draw()`: the rows, after asking `growth` for the height they need.
  - `run()`, async: reads the keyboard and draws, until a command or the terminal ends it. On leaving, what is still being sent or
    stopped is cancelled.

## Using it

- Enter clears the line at once. The message goes into the outbox, which runs one item at a time, in the order typed. If the model
  is busy, or something is already queued, the bar says "queued", and shows how many wait.
- Each item waits for the whole turn, so the queue never cuts into one: a message typed while the model makes tool calls goes in
  after the calls are run and the model has answered them.
- **Ctrl-C forces the queue in.** While busy it starts one `stop`; a second press while it runs does nothing more. The model hands
  over within a fraction of a second, even if its server is silent ([openai.md](../../providers/openai.md)). The stop message
  overtakes any cue, so calls not yet run are dropped, the turn is over, and the queue goes in, one item per turn.
- An item that fails is reported under the prompt ("not sent: ..."); the next one still goes. A typed line is in the history.
- A command may be `async`: the bar runs it beside the keyboard and reports what it raises.
- `send`, `stop`, `quit` and `busy` are parameters so a test, or a different session, can put its own in.

## Why it is this way

- **A message waits for the whole turn, not for the holder.** A turn passes the log from program to program: the model releases it
  with a cue for the tool runner, which only then claims. A message that claimed as soon as the model let go would already be first
  in the queue, land after the runner's cue, and the calls would never run. So `after_turn` takes the turn with `cues.take_turn`,
  which claims only once nobody holds the log and no cue is last, and looks again once it has the log.
- **Only stop cuts a turn short.** A queued item claims at `PRIORITY`, 0, a provider's default, so a provider holding the log is not
  `outranked()` by it even in the moment between the bar's look and its claim. Priority decides who goes first among claims; the
  waiting is `take_turn`'s. Stopping alone claims above.
- **The stop is a user message.** It tells the model, in the next turn, why its last reply ends where it does. It has no cue: nothing
  should answer it.
- **Everything that writes for the user goes through one queue.** Sending at once when the model is idle and queueing when it is
  busy were two paths that did the same thing, so there is one: wait for the turn, then claim. When the model is idle the wait is
  one read. `/continue` is in the same queue, so it lands where it was typed among the messages.
- **Work runs beside the keyboard.** Sending, stopping and an async command are tasks on the bar's loop, so typing never waits for the
  log. Each ends by waking the loop, which draws what changed.
