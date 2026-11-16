# `std/panels/logviewer/ansi.py`: width, wrap, pad, strip, cut, highlight

Text with colour codes, measured and cut in terminal cells.

```python
width("\x1b[1mhé中\x1b[0m")       # 4: colour codes take none, 中 takes two
wrap(line, 40)                     # rows of at most 40 cells, the colour carried over
```

- `cell_width(ch)`: 0 for a combining mark, 2 for a wide character, else 1. `width(text)`: the cells text takes.
- `wrap(line, cols)`: rows of at most `cols` cells; a colour carries over, every row ends reset. Escapes other than colour are dropped.
- `pad(row, cols)`: exactly `cols` cells. `expand_tabs(line)`. `strip(text)`: without escapes.
- `cut(text, start, end)`: the characters of plain text in those cells. `highlight(row, start, end)`: those cells in reverse video.

## Why it is this way

- **The viewer lays text out itself**, so it must know how many cells a line takes and where to break it, without losing the colour a
  broken line was in.
- **Escapes other than colour are dropped.** The viewer owns the screen; a message must not move the cursor or set the title.
- **Printable ASCII takes a fast path.** Nearly all text is ASCII with a few colour codes, and wrapping runs on every layout.
