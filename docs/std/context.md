# `std/context.py`: ContextRenderer, render

A context renderer is a step between a log and a program that reads it as a conversation. It takes the log's entries and returns
the entries that program should go on. A provider is given a list of them, as a viewer is given box renderers.

```python
def without_errors(entries):                       # a ContextRenderer
    return [e for e in entries if e.tags[:1] != ["error"]]

OpenAI(context=[void.CONTEXT, without_errors]).run()
history = chat(render(entries(log.read()), [void.CONTEXT, without_errors]))
```

- `ContextRenderer`: `(list[Entry]) -> list[Entry]`.
- `render(entries, renderers)`: the entries as each renderer in turn leaves them. No renderers: the entries, unchanged.

## Using it

- A renderer may drop entries, reorder them, or put new ones in (a summary in place of old turns). It must not change the log: it
  is given entries, not a writer.
- Order matters: each gets what the one before it left.
- A renderer runs on every reply, over the whole log. Keep it linear.

## Why it is this way

- **Between the log and the provider, not in either.** The log holds everything that happened. What a model is sent is a view of
  it, and that view is a choice the start script makes. In the log, a "hidden" message would be hidden from every program; in the
  provider, every provider would have to know every reason a message is left out.
- **Entries in, entries out.** A renderer knows [conversation.md](conversation.md) and nothing about any model API, so the same
  one works for every provider. Rendering to an API's messages stays the provider's (`chat`).
- **A list in the start script.** Like tools and box renderers, they are values handed out where the programs are started.
  Nothing registers itself.
