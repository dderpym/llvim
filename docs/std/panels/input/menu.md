# `std/panels/input/menu.py`: Menu

The suggestions shown as you type: which are shown, which is chosen, and when the menu stays shut.

```python
menu.refresh(complete(text, cursor, commands), text)
menu.move(1)
chosen = menu.current()
```

- `refresh(items, line)`: the suggestions for the line now. A choice is kept while its suggestion is still there.
- `move(delta)`: the next or previous suggestion, round to the other end. `current()`: the chosen one, or `None`.
- `dismiss(line)`: shut until the line changes. `open()`: shown again. `shown`: there are items and it is not dismissed.

## Why it is this way

- **Esc shuts it for this line only.** A menu that came back on the next key would make Esc useless; one that stayed shut for good
  would hide suggestions for the next command.
