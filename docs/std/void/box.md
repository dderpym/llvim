# `std/void/box.py`: BOX

The viewer's renderer for voided messages. It claims each one and shows nothing.

```python
Viewer(renderers=[void.BOX, bash.BOX]).run()
```

## Using it

- List it before the other renderers. The first renderer to claim a message gets it ([box.md](../panels/logviewer/box.md)), so
  after `bash.BOX` a voided bash call would still be drawn as a terminal.
- Plain output (`--plain`, a pipe) leaves voided messages out too: their box has no text.

## Why it is this way

- **The built-in hidden box.** Cues are already shown as nothing by `boxes.Hidden`. A voided message is the same to the viewer, so
  it uses that box and adds only the claim.
- **Nothing, not a marker.** The picker is where voided messages are listed and restored. A grey "voided" line for each in the
  viewer would keep in sight what the user asked to be rid of.
