# `std/panels/input/pane.py`: Growth

Makes the input pane as tall as what it holds: its usual rows, plus what the menu or a long message needs.

```python
growth = Growth(base=3)
growth.want(extra=4)          # four rows more, laid out in one select-layout
```

- `Growth(base=3, run=tmux, pane=$TMUX_PANE)`:
  - `want(extra)`: be `base + extra` rows tall, but never more than about half the window. Zero is the usual height.
  - Outside a pane, or when the window is not a stack of full-width panes, or tmux refuses: nothing happens.
- `fit`, `stack`, `checksum`: the heights of the stack, and the tmux layout string for them.

## Why it is this way

- **It reads the panes each time, and remembers nothing.** It lays the window out again with its own pane the height it wants, the
  panels below and above it as they are, and the top one taking or giving the rest, in one `select-layout`. A saved layout restored
  afterwards flashed, and carried the focus with it.
- **Only a stack is laid out.** A layout someone made by hand is not ours to undo.
