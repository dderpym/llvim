# `std/panels/logviewer/boxes.py`: Thinking, Markdown, Hidden, Fallback

The built-in boxes, each a function of its messages, and `BUILTIN`, their renderers in the order they are tried.

```python
chain([mine])          # [mine, thinking, markdown, hidden, fallback]
```

- `Thinking`: a message tagged `thinking`, its markdown all in grey. In full while it streams; finished, it folds to one line
  (`▸ [thinking] 120 words · click to open`) and a click opens and folds it.
- `Markdown`: an `assistant` message, its markdown drawn at the width, with two blank rows under it once finished.
- `Hidden`: a cue. It shows nothing.
- `Fallback`: anything: the tags in bold, then the content. A streaming message is left open, with no blank rows.
- `Static(host, messages, fn)`: a text function `fn(tags, content)` as a box; see [render.md](render.md).

## Why it is this way

- **The fallback claims everything.** There is always a box, so there is no "no renderer" case.
- **Thinking and markdown copy what was written.** Their `text` hook is the message as written and they are not framed, so plain
  output and copying keep every character, while the screen shows it drawn.
- **Cues are hidden.** A cue is for the programs: the reply under it shows that it was answered.
