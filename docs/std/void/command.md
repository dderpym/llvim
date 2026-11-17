# `std/void/command.py`: COMMAND

`/void` in the input bar claims the log once the turn in progress is over, opens the [picker](picker.md) in a tmux popup over
the session, and hands it the claim. The popup closes when the picker does.

```python
Input(commands=[*STANDARD, void.COMMAND]).run()
```

- `popup(log, address, client=None)`: the `tmux display-popup` command that runs `llvim-void --adopt address` for the log, 80% of
  the screen, in the project folder.
- `terminal_client()`, async: the client of this session that a person looks at, or `None`.
- `show(log, notice)`, async: the queued work. It claims the log with `cues.take_turn`, offers the claim, starts the popup, and
  returns when the popup closes. A popup that ends without a picker taking the claim, or none within 10 seconds: the log is
  let go, and a notice says why.
- Outside tmux, `/void` says so and starts nothing. `llvim-void` still works there, in the terminal it is run in.

## Using it

- It is queued like a message ([bar.md](../panels/input/bar.md)): typed while the model works, it opens when the turn is over, and
  Ctrl-C stops the model to get there sooner. What you send after it waits until the picker has closed.
- Needs tmux 3.2 or later, for popups.
- The picker gets `PATH`, `LLVIM_STORE` and `LLVIM_HOME` from the input bar. A popup starts from tmux's environment, not from the
  pane it was asked from, so without them it could open another store.

## Why it is this way

- **A popup, not a mode of the input bar.** The bar is three rows, and a command there can only say a line and queue work
  ([commands.md](../panels/input/commands.md)). A history list wants most of the screen. A popup is tmux's own way to put a
  program over the session for a moment, and the bar needed no change.
- **The bar claims; the picker is handed the claim.** The claim then waits in the log's queue like a message's: the status line
  and the others see it, and it gets the log in its turn. The picker opens only when the claim is granted, and holds the log from
  its first frame. The picker claiming for itself was rejected: the popup would open first and wait, or the bar would wait
  without a claim and something could take the log in the moment between.
- **The whole turn, not only the holder.** Between the model's reply and its tool calls nobody holds the log. A claim granted
  there would hold it with the calls still waiting, and they would run as the picker closed, after what you voided.
- **The client is named.** The viewer and the tool runner are attached to the session too, as control-mode clients. tmux may send
  a popup to the most recent client, and one sent to a control client shows nowhere.
- **The picker is a command of its own.** `llvim-void` can be bound to a key in `tmux.conf`, or run against another log, without
  the input bar.
