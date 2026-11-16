# `config/tmux.conf`: the tmux config

The config `llvim` starts its tmux server with ([cli.md](../cli.md)).

- **No keyboard bindings** but a way out: **Ctrl+Alt+Q** kills the llvim tmux server.
- **A few mouse bindings:** click to focus, drag a border to resize, Alt+drag to move a floating pane, and the **wheel** to scroll
  back through a pane's history.
- Status bar off, a large scrollback, truecolor, extended keys, and `window-size latest`, so several clients on one session follow
  the newest.
- `LLVIM_HOME`, `LLVIM_STORE` and `LLVIM_MODEL` are taken from the client that starts each session.

## Why it is this way

- **tmux is only the host.** The panels draw their own screens and route their own keys ([keys.md](../std/panels/keys.md)), so
  tmux's keys would only get in their way. Every key table is cleared (`unbind -a` alone only clears the prefix table). Ctrl+Alt+Q
  reaches tmux as an ordinary escape sequence in any terminal and is rarely taken by one.
- **The wheel leaves history by itself.** It enters tmux's history view three lines a notch, and scrolling back to the end leaves
  it, so no key is needed to get out. A program that asks for the mouse gets the wheel itself.
- **Every terminal may set the clipboard**, so the viewer can copy a selection with OSC 52, which tmux passes on and keeps.
- **Settings come from the client.** A tmux server keeps the environment it started with, so a later `llvim` from another shell
  would not pass on its store or model. `update-environment` makes each new session take them from the client that starts it.
