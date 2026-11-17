# `std/void/picker.py`: Picker, llvim-void

The list where you void messages and put them back. It holds the log for as long as it is open. `/void` shows it in a popup ([command.md](command.md)); `llvim-void [log]
[-p project]` runs it in any terminal.

```
enter: void from here on · v: void or restore · tab: open a turn · a: hide voided · esc: close
 ▸   1  list the files
 ▾   2  now delete them                                              ◐
          user  now delete them
          assistant  I'll do that.                                VOID
          tool_call bash  {"command": "rm a.txt"}                 VOID
 ▸   3  what is left?
```

- It opens on the last turn. Up and Down (or `k` and `j`) move.
- **Enter** voids the chosen row and everything after it, to the end of the log, and closes. It never restores.
- **`v`** (or Space) voids the chosen row alone: a turn, or one element of an open turn. On a row that is all voided, it restores
  it. The picker stays open.
- **Tab** (or Right) opens a turn into its elements ([turns.md](turns.md)); Left shuts it.
- **Esc**, `q` or Ctrl-C closes.
- A row is marked `VOID` when all of it is voided, and `◐` when part of it is.
- **`a`** shows the rows that are all voided, or hides them again. They are hidden when the picker opens. A turn voided in part
  is always shown. When `v` hides the chosen row, the row now in its place is chosen.
- `Picker(log, screen, writer)`: the list, over a log it is given held.
- `pick(log, screen, address=None)`, async: runs the picker with the log held, and lets it go when the picker closes.
  - With `address` (`llvim-void --adopt ADDRESS`): it adopts the claim offered there ([handoff.md](../../core/handoff.md)). This
    is how `/void` opens it.
  - Without: it claims the log itself. While the claim waits, one line says so, and a closing key gives up.
- `set_void(writer, log, ids, void)`, async: puts the tag on those messages, or takes it off, in one commit signed as you.

## Using it

- Nothing else writes the log while the picker is open: the model does not answer, tools do not run, and a message you had queued
  waits. Close it to let them go on. The status line says *busy: /void* meanwhile.
- `/void` opens it only once its claim is granted, and hands it that claim ([command.md](command.md)). Run on its own while the
  log is in use, `llvim-void` waits for it and says so.
- Each Enter or `v` is one commit, made at once, so the viewer behind the popup shows it and `restore` can undo it.
- A cue nobody has answered can be voided with its turn, which ends the turn ([tag.md](tag.md)).

## Why it is this way

- **Two keys for two questions.** "Go back to here" is the common one, so it is Enter, and it closes. "Take this out" is `v`, and
  it stays open because it is often done to several rows.
- **Whole turns first.** A long log is a few dozen turns and hundreds of messages. The elements are one key away for the turn you
  care about.
- **It holds the log while it is open.** The list is then the log: no reply arrives under the row you are about to void, and
  Enter's "everything after" is everything. Claiming for each key was rejected. The picker then had to follow the log, wait in
  the middle of a keypress, and decide what "after" meant for messages written during the wait.
- **It commits each change, not all on closing.** A picker that is killed, or a popup that is closed from outside, loses nothing
  that was shown as done.
- **What is voided is hidden until asked for.** Voided turns pile up, and the list is for choosing what to void next. Restoring is
  rarer, so it costs one key, `a`, to see them. A turn voided in part stays: some of it is still sent, and its other elements may
  be voided next. Numbers keep counting the hidden turns, so a gap shows where they are.
- **`v` toggles, Enter does not.** One key that voids and restores makes a mistake one keypress to undo. Enter covers many rows
  in different states; restoring some and voiding others would be a guess.
