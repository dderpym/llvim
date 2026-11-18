# `std/void/turns.py`: Turn, Element, turns

The log as the [picker](picker.md) lists it: turns, each made of elements. An element is what is voided together.

```python
for turn in turns(entries(log.read())):
    turn.label, turn.voided                      # "list the files", Voided.PART
    for element in turn.elements:
        element.label, element.voided, element.entries
```

- `turns(entries)`: the turns, oldest first.
  - A turn starts at a message the user wrote and runs to the next one. Messages before the first user message are a turn too.
  - The note a stop leaves (`["user", "stop"]`) does not start a turn. It belongs to the turn it stopped.
- An `Element` is one message, except:
  - a tool call, its start and its result are one element, found by call id;
  - a cue is not an element. It joins the element before it;
  - a snapshot record ([snapshot.md](../snapshot.md)) is in no element at all, so the cue after it joins the user message.
- `voided`, on a turn or an element: `Voided.NONE`, `PART` or `ALL` of its messages.
- `label`: the tags and the first line of text of its first message. A turn that starts with a user message is labelled with the
  text alone.
- `id`: the id of its first message, which stays the same while the log grows.

## Using it

- Voided messages are grouped as what they were ([tag.md](tag.md)), so a voided turn is still a turn in the list.

## Why it is this way

- **Turns from messages, not commits.** One turn is several commits: yours, the model's, two for each tool call. The messages say
  where a turn starts; core has no list of commits to offer, and none is needed.
- **A call and its result are voided together.** A model API refuses a result without its call. The viewer shows them as one box
  too, so one row in the picker is one thing on screen.
- **A cue goes with what it asks about.** A cue left alone after its message was voided would still be answered, by a model that
  was not sent the message.
- **Snapshot records are not listed.** A record is the program's note of what it kept, not part of the conversation: the model is
  never sent one, so voiding it would change nothing. Left in, it would also sit between a user message and its cue, and take
  the cue away from the message. Voiding a turn leaves its record as it is, so `snapshot.at` still finds the turn's snapshot.
