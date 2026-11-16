# `std/panels/input/complete.py`: complete, Suggestion

What to suggest for the line being typed.

```python
complete("/qu", 3, commands)       # [Suggestion("/quit", 0, 3, "end the session")]
command_name("/quit now")          # "quit"
```

- `complete(line, cursor, commands)`: while the cursor is in the first word, the commands whose names start with it; after a command
  and a space, what its `complete` gives for the rest. Nothing for a line that does not start with one `/`.
- `Suggestion(text, start, end, help="", then="")`: replace `line[start:end]` with `text`, then `then` (a space, for a command that
  takes an argument).
- `command_name(line)`: the command a line names, or `None` if it is a message (`/etc/hosts`, `//quit`, `/ hi`).

## Why it is this way

- **A command is a word right after the slash, followed by a space or the end.** So a path or a slash in prose is a message, and
  `/qiut` is caught as an unknown command instead of being sent to the model.
