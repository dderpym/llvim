# `std/tools/bash/tool.py`: TOOL, TERMINAL

The bash tool. It runs `bash -c <command>` in the project folder, in a [terminal](terminal.md) the user watches, and tells the model
what it printed.

```python
await Registry([TOOL]).run("bash", '{"command": "make test", "timeout": 300}', ctx)
```

`TERMINAL` is the `terminal` tool: a terminal that stays open, which the model and the user take turns at
([shared.md](shared.md)).

```python
await registry.run("terminal", '{"command": "python3"}', ctx)                    # ">>>", running in terminal call_1
await registry.run("terminal", '{"id": "call_1", "keys": "2 ** 10\\n"}', ctx)    # "1024"
await registry.run("terminal", '{"id": "call_1", "give_to_user": "pick a name"}', ctx)
await registry.run("terminal", '{"id": "call_1", "close": true}', ctx)
```

- Parameters: `command`; `timeout`, in seconds (default 120, see [settings](settings.md)); `interactive`.
- `interactive` means interactive for the user, not the model: the model cannot type into a command. The model sets it only when
  the user must type, as for `sudo`, a REPL or an editor. The box then offers *click to type*. When false, the command's input is
  closed, so `cat` with no file ends at once.
- The result is what the command wrote ([terminal.md](terminal.md)):
  - not interactive: stdout and stderr, byte for byte, in the order written (invalid UTF-8 becomes U+FFFD);
  - interactive: its screen as the user saw it, without the empty rows under the last line.

  Then, by how it ended:
  - exit 0: the output, or `(no output)`;
  - any other exit: the output and `[exit code N after 2.3s]`, with the signal named when N is 128 plus one
    (`[exit code 137 (SIGKILL) after 2.3s]`). This is not an error result: the command ran;
  - still running at its timeout: an error result, `[timed out after 120s and stopped]`;
  - cancelled by the runner: an error result, `[interrupted after 2.3s]`;
  - outside tmux: an error result that says it needs a tmux terminal.
- `terminal` parameters: one of `command`, `keys`, `give_to_user` (what the user should do) and `close`, or none; `id`, the
  terminal, for all but `command`; `timeout`.
  - `command`: starts it on a new terminal (`shared.start`), kept under this call's id.
  - `keys`, or none of them: types (or not), and waits for the screen to be still for `settle` seconds, up to `timeout`.
    Nothing is stopped when `timeout` runs out.

  The result is what is new ([shared.md](shared.md)), then:
  - still running: `[running in terminal <id>: ...]`, after `the user handed it back.`, `the user did not hand it back within
    3600s; it is yours again.` or `still printing after 120s.` as it applies;
  - exited or closed: `[exit code N; the terminal is closed]`, or `[stopped; ...]` if it had to be killed;
  - interrupted: an error result, `[interrupted; still running in terminal <id>]`;
  - no such terminal, no `command` or `id`, or two of `command`, `keys`, `give_to_user` and `close`: an error result that says
    so.
- Output over `max_lines` lines or `max_bytes` bytes is saved to `/tmp/llvim-out-<random>.log`, readable only by you. The model
  gets a note instead: where the file is, its size and line count, how long the command ran, the shape of its lines (`3 lines >=
  10 KB (lines 5, 900, 2000); median line 40 B`), and a preview of whole lines from its start and end.

## Using it

- It is an async tool. It waits on the terminal in the runner's loop, and a stop cancels it like any other.
- A command that is not interactive does not have a terminal on its stdout. Most programs then print plain text, without colour,
  progress bars or columns (`ls` prints one name per line). The tool's description tells the model this.
- An interactive command's result is the screen: escape codes and carriage returns are applied and gone, and tmux's
  `history-limit` bounds how much is kept.
- The saved files are left for the system's temp cleaning.

## Why it is this way

- **Large output goes to a file, with a note.** A model fed 5 MB of build log loses the conversation. The note says enough to
  `grep` well: how big, where the long lines are, what the start and end look like.
- **The preview is whole lines.** A fragment looks like a short line that is not there. A line too long for the preview is cut and
  labelled `…(line 1, 195 KB, excerpt mid-line)…`.
- **A failing exit is not a failed call.** The model ran a command and should see what it said. An error result is kept for when
  the tool itself could not do its job.
- **The bytes, not the screen, unless the user types.** The model reads output to act on it: to edit a file it `cat`ed, to match
  a diff, to see CRLF line endings. A screen loses exactly those things: trailing spaces, carriage returns, what an escape code
  did. The screen is kept only where the command needs a terminal, because the user types into it, and there what the user saw is
  what matters.
- **A terminal is its own tool, start to close.** `bash` runs a command and returns when it ends. A terminal is started, typed
  into, handed over and closed over many calls. A `bash` parameter that started one (`keep_open`) was rejected: it split one
  thing across two tools, and gave `timeout` two meanings in one tool.
- **`interactive` stays on bash.** One call that the user types into until the command exits is still the simplest way to run
  `sudo` once. `terminal` is for when the model has to read and answer too, or hand over in the middle.
- **The user's turn is a call that waits.** The model's turn does not end while the user types: its `terminal` call is still
  running, and returns when they hand back. Ending the turn and starting a new one on hand-back would need a cue the runner
  understands, for no gain. Typing in the input bar outranks the call as it does any other, which ends the user's turn.
- **Nothing is trimmed.** Trailing spaces and blank lines are the command's output. Removing them made the model see a file that
  was not the one on disk.
