# `std/panels/logviewer/text.py`: clean, default, thinking, partial

The colours of the built-in renderers, cleaning untrusted text, and how a message looks as plain terminal text.

```python
default(["assistant"], "hi")      # "\x1b[1;36massistant\x1b[0m\nhi\n\n"
partial(["assistant"], "h")       # its start, while it streams
```

- `clean(text)`: the text without control characters, but with line breaks and tabs.
- `tags_text(tags)`: the tags, space-separated; one that is not a string as JSON.
- `default(tags, content)`, `thinking(tags, content)`: a finished message, the tags in colour over the text.
- `partial(tags, text)`: a message still streaming: no closing line break, and thinking's grey left on.
- `CLEAR`: reset, then clear the screen and its scrollback.

## Why it is this way

- **Message text is untrusted.** It comes from a model or a web page. Control characters would let it drive the terminal (clear the
  screen, set the clipboard with OSC 52), so only `\n` and `\t` survive.
- **A streaming message is the start of the finished one.** The printer prints only what is new ([plain.md](plain.md)).
- **`CLEAR` starts with a reset.** A grey stream cut short must not leave the next text grey.
