# `std/panels/input/editor.py`: Editor

The line being typed: its text, its cursor, and the history. Plain logic, with no terminal in it.

```python
editor = Editor(history)
handle(editor, b"h"); handle(editor, b"\x1b[D")    # type, move left
text = editor.submit()                             # into the history, and the editor is empty
```

- `Editor(history=None)`: `insert`, `backspace`, `delete`, `kill_to_end`, `kill_to_start`, `kill_word`, `newline`, `left`, `right`,
  `home`, `end`, `word_left`, `word_right`, `history_prev`, `history_next`, `set`, `clear`, and `submit()`, which returns the text.
- `handle(editor, raw)`: applies a key from `KEYS` (emacs-style keys, arrows, Shift-Enter) or inserts printable text. `False` if
  the key is neither.
- `load_history(path)`, `save_history(path, history)`: the last 1000 entries, one JSON string a line.

## Using it

- Walking back through the history keeps what was being typed, and walking past the newest entry brings it back.
- `submit` leaves out a blank line and one that repeats the last entry.
- A history that cannot be saved is not an error: the bar goes on without it.

## Why it is this way

- **No terminal in it.** What a key does to a line is the part with the most cases, so it is plain code tested without a screen.
- **One JSON string a line.** An entry can hold line breaks, and a plain line from an older file still loads as itself.
