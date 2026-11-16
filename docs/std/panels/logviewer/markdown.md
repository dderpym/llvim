# `std/panels/logviewer/markdown.py`: render

Markdown as rows of coloured terminal text for a given width.

```python
rows = render("**hi** there\n\n- one\n- two", cols=40)
grey = render(text, cols=40, tone="\x1b[38;5;245m")      # all in one colour, the styles kept
```

- `render(text, cols, tone=None)`: the rows. Blocks: paragraphs wrapped at words, headings, bullet, numbered and task lists (nested),
  block quotes, fenced code on a darker ground with its language, tables (bordered, narrowed to fit, cells wrapped), rules. Inline:
  `code`, **bold**, *italic*, ~~strike~~, links (the text, then the address in grey) and bare URLs.

## Using it

- A piece not closed yet (`**bold`, a fence, half a table) shows as the text it is until its end arrives.
- No syntax highlighting, images or HTML. What it does not know shows as written.

## Why it is this way

- **No state, no dependencies.** The same text and width give the same rows, so a streaming message is simply rendered again each time
  it grows.
