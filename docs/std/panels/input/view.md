# `std/panels/input/view.py`: render

What the input bar looks like: the prompt at the bottom, the menu above it. A function of the state and the size of the pane.

```python
rows, cursor = render(editor, menu, notice, cols, rows)
screen.draw(rows, cursor)
```

- `render(editor, menu, notice, cols, rows)`: the rows to draw, and the cursor as `(column, row)` or `None`.
- `wanted(menu)`: rows the menu would like; `prompt_height(editor, cols)`: rows the text needs, at least `INPUT_ROWS` (3).
- `cut(text, cols, cursor)`: the text in rows of at most `cols` cells, and where the cursor is.

## Using it

- The prompt takes the rows its text needs and the menu what is left; with too few rows it scrolls to keep the cursor in view.
- A notice shows under the text when there is a free row.

## Why it is this way

- **A pure function.** The bar asks for rows and draws them, so what the bar looks like is tested without a terminal.
