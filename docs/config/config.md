# `config/`: what `llvim` starts with

| File | What it defines |
|---|---|
| [start.py](start.md) | The shipped start script: the viewer, a status line and the input bar, and the provider |
| [tmux.conf](tmux.md) | The tmux config: no keys but a way out, the mouse, and settings from the client |

## Why

- **Two kinds of choice.** The start script is yours to copy and change: it is the layout and what runs in it. The tmux config is
  fixed: it only keeps tmux out of the way of the programs in the panes.
