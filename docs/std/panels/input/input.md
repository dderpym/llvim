# `std/panels/input/`: Input, the input bar

`llvim-input [log] [-p project]` is where you write to the log. Type, press Enter, and it is committed as a `["user"]` message with a
cue for the model, signed with your user name.

```python
Input(commands=[*STANDARD, my_command]).run()    # the log is the session's (env.log)
```

| File | What it defines |
|---|---|
| `__init__.py` | `Input`, the program; `main`, the command; `STANDARD`, the commands it has by default: `/quit`, `/exit`, `/help`, `/continue` |
| [bar.py](bar.md) | `Bar`, `send`, `stop`: what each key does, sending, and the loop |
| [editor.py](editor.md) | `Editor`: the line being typed, its cursor and its history |
| [commands.py](commands.md) | `Command`, `Context`, `@command`, and `/quit`, `/exit`, `/help` |
| [complete.py](complete.md) | `complete`, `Suggestion`: what to suggest as you type |
| [menu.py](menu.md) | `Menu`: which suggestions show and which is chosen |
| [view.py](view.md) | `render`: the rows of the bar at a size |
| [pane.py](pane.md) | `Growth`: the pane's height, set from what it holds |
| [generate.py](generate.md) | `/continue` |

## Using it

- It needs a terminal: off one, it exits saying so.
- **Enter** sends, or queues while the model works ([bar.md](bar.md)); **Shift-Enter** inserts a line break where the terminal tells it apart from Enter (through tmux, terminals with
  xterm's modifyOtherKeys do; kitty does not). **Ctrl-C** stops the model if it is working, which forces the queue in, else clears the line. **Ctrl-D** does
  nothing, so the pane is not closed by accident. **Ctrl-L** redraws. **PageUp** and **PageDown** go to the viewer without the focus.
- A line that starts with `/` and a word is a command, and typing the slash opens a menu above the prompt. **Tab** takes the only
  suggestion or steps through them, **Up** and **Down** move while it is open, **Esc** closes it until the line changes. An unknown
  command is reported, not sent; start the line with `//` to send text that begins with a slash.
- The history is kept in `$LLVIM_HOME/input_history`.

## Why

- **Its own screen, not `input()`.** A menu above the prompt and text over several rows cannot be done with readline.
- **The parts know nothing of each other.** The editor knows no terminal, the view is a function of the state and the size, and the
  bar takes its screen, panes and growth as parts, so each is tested alone.
- **Commands are values the bar is given.** Nothing registers itself, so a session's bar has the commands its layout gives it.
