# `std/panels/logviewer/document.py`: Document, Slot

The log as slots, each a group of messages one renderer claimed under one key, shown by one box. A slot's box is made, and its rows
worked out, only when it comes into view.

```python
doc = Document(host, renderers)
doc.sync(log.read())
anchor, offset = doc.end_position(rows, cols)
window = doc.window(anchor, offset, rows, cols)   # the rows, and where each slot is on screen
```

- `sync(snapshot)`: takes the log as the snapshot has it. `True` if what is shown may be different.
- `window(anchor, offset, count, cols)`: `count` rows from the anchor, laying out only the slots they come from.
- `end_position(count, cols)`, `move(anchor, offset, delta, count, cols)`: the anchor at the end; scrolling from one.
- `box_of(slot)`, `rows_for(slot, cols)`: the slot's box, made or updated now, and its rows at a width.
- `replace_failed()`: puts the fallback in for any box that raised. `stale()`: something changed that no box said.
- `close()`: closes every box.

## Using it

- A slot whose messages change gets them through the box's `on_messages`; a box without one is made again ([box.md](box.md)).
- A box that draws itself is laid out again only when it says it changed, when the width changes, or after `stale()`.

## Why it is this way

- **A place is an anchor, not a row number.** Most slots were never laid out, so their heights are unknown. An anchor is a slot and how
  many of its rows are above the screen; scrolling walks from it, laying out what it passes, and the end is found by walking back from
  the last slot.
- **A sync redoes only what changed.** Messages are ordered by id, and the ones before the first uncommitted one that are the same as
  last time keep their groups. Only the messages from the first difference on are taken out of their slots and claimed again. So a
  streamed chunk costs about a third of a millisecond at 5,000 messages, and a commit costs the messages it committed.
- **A slot outlives its messages leaving.** A message that leaves and comes back to its group (the streaming message, each chunk;
  every uncommitted message, at a commit) gets its old slot, and box, again. So a box keeps its state, and an anchor on it stays put.
- **Slots keep the order of their first messages.** A slot that keeps a message from before the difference sat there already; one
  made again starts after it. So putting slots back in the order they were made is the order of their first messages.
