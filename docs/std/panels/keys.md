# `std/panels/keys.py`: Outcome, Redirect, route, Panes, parse

What a panel does with a key, and how a key moves to another panel. tmux gives the keyboard to the focused pane, so a panel that does
not want a key must be able to hand it to one that does.

```python
decision = route(raw, own_keys, lambda raw: Redirect("input", raw))
if isinstance(decision, Redirect):
    panes.apply(decision)                    # send-keys to the input pane, and focus it
```

- `parse(data)`: what the terminal sent, as `Key(raw)` and `Mouse(button, x, y, press)` events. An escape sequence is one key.
- `Outcome.HANDLED`, `Outcome.PASS`, and `Redirect(panel, keys=b"", focus=True)`: the decisions about a key. A handler is
  `raw -> decision`.
- `route(raw, *handlers)`: the first decision that is not `PASS`, asking in order; `PASS` if none has one.
- `Panes(run=tmux, here=$TMUX_PANE)`:
  - `id(name)`, `known(name)`: the pane of the panel named `name`, from the window option `@llvim_pane_<name>`. Asked once and
    remembered. Outside tmux, or for this panel itself, `known` is false.
  - `apply(redirect)`: sends the keys (`send-keys -H`) and, if `focus`, selects the pane. `False` if the panel is unknown or
    tmux refused; a refused pane is looked up again next time.
- `over(control)`: runs `Panes`' commands over a [Control](../tmux.md) connection, or a function that makes one when first asked.
- `UP`, `DOWN`, `PAGE_UP`, `PAGE_DOWN`, `HOME`, `END`, `WHEEL_UP`, `WHEEL_DOWN`: what a terminal sends for them.

## Using it

- A redirect moves the focus too, so only the first key of a run is forwarded; the rest go straight to the panel that wants them.
- The panes are named by whoever lays the session out, with `tmux set-option -w @llvim_pane_input %3`. With none, every redirect
  does nothing, and a panel on its own still works.

## Why it is this way

- **A key is a decision, made by a chain.** A panel's own keys come first, then shared keymaps it chooses, then a default: the viewer
  and the bar send what they do not use to each other. A vim mode later is one more handler at the front of the chain, with nothing
  here to change.
- **Panels are found by name, in tmux.** The layout is the only thing that knows where each panel is, and tmux options are where it
  can say so without a file or a server of its own.
- **Raw bytes go through.** `Key.raw` is exactly what the terminal sent, so a key passed to another program arrives unchanged,
  modifiers and all.
