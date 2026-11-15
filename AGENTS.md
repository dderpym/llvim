# AGENTS.md

How llvim is built, documented and tested. Read this before changing anything.

## Build and run

```
nix develop                  # uv, python 3.12, git, tmux (optional: any machine with these works)
uv sync                      # makes .venv; the commands land on PATH inside the nix shell
uv run pytest                # everything
uv run pytest tests/core     # one area
```

- Source lives in `src/llvim/`, built with `uv_build`. Commands are added as `[project.scripts]` in `pyproject.toml`.
- Dependencies: none at runtime unless there is no reasonable way around one. Dev tools go in `[dependency-groups] dev`.
- `flake.nix` builds the package (tests run as its check) and puts tmux and git on the commands' PATH.

## Layout

Three trees with the same shape:

| Tree | What |
|---|---|
| `src/llvim/` | The code. `core/` is the model and depends on nothing else in llvim; `std/` is the standard library built on core. |
| `docs/` | One page per source file, at the mirrored path: `src/llvim/core/log.py` → `docs/core/log.md`. Each folder has a page named after it (`docs/core/core.md`). |
| `tests/` | One test file per source file, at the mirrored path: `src/llvim/core/log.py` → `tests/core/test_log.py`. |

A change to a file changes its doc page and its test file in the same commit.

## Code explains what; comments and docs explain why

- Code says what it does through its names and shape. If a reader needs a comment to know *what* a piece of code does, rewrite the code instead:
  a better name, a smaller function, a named variable for the intermediate value.
- A comment, docstring or doc page explains *why*: the reason for a choice, the constraint behind it, the alternative that was rejected,
  the bug it prevents. If the code is obvious and there is no why, there is no comment.
- No comments that restate the line below, narrate steps (`# loop over messages`), mark sections of obvious code, or record history
  (`# changed to fix X`; that belongs in the commit message). No commented-out code.
- A docstring is there only when the name and signature leave something out a caller must know. One line is usually enough.

## Docs

A doc page says **why a file's classes are shaped the way they are**. It is not an API dump, and it does not repeat what the code already says.

- Title: the file and what it defines: ``# `core/writer.py`: Writer``.
- Open with one or two sentences on what the thing is, then a short code example of using it.
- Sections, in this order where they apply:
  - the signature and its cases, as a list (`Held and wait=False: raises Busy, ...`);
  - **Using it**: only what a caller cannot see in the signatures: when a call fails, what it costs, what must happen in what order;
  - **Why it is this way**: each decision as a bullet that starts with a bold claim (`**No forcing.**`) and then the reason, including what was rejected.
- A folder page has a table: `| File | What it defines |`, linking each page, then a "Why" section for the folder as a whole.
- Plain, short sentences. Say what something does, not what it "provides" or "enables". No marketing, no "simply", no "powerful".
- Link the page you mention (`[lock.md](lock.md)`) the first time it comes up.
- The README lists the doc pages; a new page is added there.

## Tests

The tests are an accessory to the source tree. A test file tests its one module and nothing else, and reads like that module's doc page:
its tests are sentences about what the module does, one behaviour each.

### How hard each part is tested

| Part | How | Why |
|---|---|---|
| `core/` | Thoroughly, with the real thing: a real git repo in a temporary store, real locks, real processes that die | Everything else stands on it, and its failures lose data. Races, crashes and the on-disk format are tested here |
| `std/` | Moderately: the main behaviours and the edges that have bitten, against **stubs** of what it is built on | A test of one module must not depend on another. A failure points at the module that broke |
| Outside the program (tmux, an HTTP endpoint) | Minimally, with a real one | Slow and different from machine to machine, so only what a stub cannot prove: that the real thing behaves the way the stubs assume |

### Stubs

- Shared stubs and fixtures live in `tests/conftest.py`, with a docstring each; a stub used in one folder lives in that folder's `conftest.py`.
- A stub of a core class has no call the real one lacks, and a test in core checks that, so it cannot drift into something the real one cannot do.
- A test that needs a real tmux is marked `needs_tmux` and is skipped where there is none.
- Tests run as if outside tmux, whatever the developer's terminal is.

### Writing a test

- Pick the module it is about and put it in the file that mirrors it. If it needs another module, stub that one.
- Name it as a sentence about the behaviour: `test_a_call_the_user_has_spoken_over_is_not_run`. If the name needs an "and", it may be two tests.
- The file's docstring names the module and says in one line what it is: `"""core/cue.py: the latest cue of a channel, ..."""`.
- Test what the module promises, not how: a fast path is tested by checking it agrees with the careful one, not by looking at the code.
- A table of cases is one test with a loop and a message saying which case failed, not one collected test per row.
- Test files may share a name in different folders (`--import-mode=importlib`).
- The whole suite stays fast (seconds, not minutes). A slow test is a bug.
