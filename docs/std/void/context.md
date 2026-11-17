# `std/void/context.py`: CONTEXT

The [context renderer](../context.md) that leaves voided messages out of what a model is sent.

```python
OpenAI(context=[void.CONTEXT]).run()
```

- `CONTEXT(entries)`: the entries that are not voided, in order.

## Using it

- Put it first in a provider's list, so later renderers never see a voided message.
- It leaves out whatever is tagged, one message at a time. The [picker](picker.md) is what voids a tool call together with its
  result, so the model is not sent one without the other.

## Why it is this way

- **Only a filter.** What may be voided together is the picker's decision ([turns.md](turns.md)). A renderer that also repaired
  half-voided calls would hide a log that some other program wrote wrongly.
