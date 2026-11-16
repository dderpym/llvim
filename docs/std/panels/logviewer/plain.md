# `std/panels/logviewer/plain.py`: Printer, follow

The log as plain text that only grows: for a pipe, `--plain` and `--once`. Scrolling, search and selection are the terminal's.

```python
await follow(log)                      # print, then print what changes, until cancelled
printer = Printer(renderers)
sys.stdout.write(printer.update(log.read()))
```

- `Printer(renderers=())`, `update(snapshot)`: the text to write to bring the terminal up to date:
  - new messages: printed after what is there;
  - a streaming message: only its new text;
  - a streaming message that finished: what closes it (`\n\n`), nothing printed again;
  - anything it cannot extend (a message removed, restored, or rendered differently once finished): `CLEAR`, then everything.
- `follow(log, once=False, renderers=())`, async: prints the log, then each change. `once`: prints it and returns.

## Why it is this way

- **What it printed is only a shortcut.** It keeps the text of each message it printed, and anything that does not extend it falls
  back to printing everything again. So a restore, or another log, is an ordinary case.
- **A streaming message is the start of the finished one.** It shows in its built-in look ([text.md](text.md)), whose text is a prefix
  of how the message prints once finished, so finishing prints only the end.
- **Each message's text is kept by id**, and made again only when the message, or whether it is committed or streaming, changes.
