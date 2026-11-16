# `std/panels/logviewer/`: Viewer, the log viewer

`logviewer [log] [-p project] [--plain] [--once]` shows a log and follows it live. On a terminal it draws the screen itself:
it scrolls, selects and copies, and shows each message with a [box](box.md). Otherwise (a pipe, `--plain`, `--once`) it prints plain
text and leaves scrolling to the terminal.

```python
Viewer(renderers=[my_renderer]).run()     # the log is the session's (env.log)
```

| File | What it defines |
|---|---|
| `__init__.py` | `Viewer`, the program, and `main`, the command; and the names a renderer needs: `Box`, `Host`, `Renderer`, `box`, `renderer`, `alone`, `render` |
| [app.py](app.md) | `Viewer`: the screen of the log, its keys and mouse, and the loop |
| [document.py](document.md) | `Document`: the log as slots, laid out only where it is shown |
| [box.py](box.md) | `Box`, `Host`, `Renderer`: what shows a group of messages |
| [boxes.py](boxes.md) | The built-in boxes: thinking, markdown, hidden, fallback |
| [render.py](render.md) | `renderer`, `render`: a text function as a renderer, and a message as plain text |
| [plain.py](plain.md) | `Printer`, `follow`: the log as text that only grows |
| [text.py](text.md) | The built-in colours, and cleaning untrusted text |
| [markdown.py](markdown.md) | `render`: markdown as rows at a width |
| [ansi.py](ansi.md) | Measuring, wrapping and cutting text in terminal cells |
| [screen.py](screen.md) | `Screen`: the terminal, taken over |

## Using it

- Up, Down, PageUp, PageDown, Home, End and the wheel scroll; scrolling back to the end follows new text again.
- Drag to select: the text is highlighted and copied when you let go (OSC 52, which tmux passes on). The copy is text: colours gone,
  a line cut to fit joined again, a box's frame left out. Escape, or a new click, lets go.
- A box that takes the keyboard gets it on a click, and gives it back on Ctrl-] or a click outside it.
- Any other key is typing: it goes to the input bar, and the focus with it. With no input bar, Ctrl-C quits.

## Why

- **One viewer, two ways of showing.** Both go through the same boxes, so a renderer works in both. On a pipe nothing is started and a
  box's plain text is printed.
- **Rows, not escape codes.** Text is measured and wrapped in cells ([ansi.md](ansi.md)), so a box is rows and scrolls with the text.
- **Only what is on screen is made.** See [document.md](document.md): a log of thousands of messages opens in about the time it takes
  to read them, and a streamed chunk costs well under a millisecond at 5,000 messages.
