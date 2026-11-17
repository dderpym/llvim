# `std/providers/openai.py`: OpenAI, respond, chat, stream

A provider for the chat-completions API that OpenAI, Ollama, vLLM, llama.cpp and others share, with only the standard library.

```
llvim-openai --configure        # save the base URL, key and model once (the key typed hidden)
llvim-openai                    # answer the log "main" of the working folder, until interrupted
llvim-openai alt -p ~/proj -m llama3 --base-url http://localhost:11434/v1
```

- `OpenAI(model=None, base_url=None, log=None, timeout=60, retries=5, priority=0, once=False).run()`: the program. The model and URL
  default to the [settings](openai_settings.md), the log to the session's. No model anywhere: it exits saying so.
- `serve(log, model, base_url, api_key, timeout, retries, priority)`, async: answers each `GENERATE` cue (`cues.receive`), until
  cancelled.
- `respond(log, model, base_url, api_key=None, timeout=60, priority=0, retries=5, backoff=1)`, async: answers if the model is cued now
  (`cues.take`); whether it wrote anything.
- `answer(log, writer, model, base_url, api_key, timeout, retries, backoff)`, async: the answer itself, with the log held.
- `chat(entries)`: the chat messages for a log.
- `stream(base_url, api_key, model, messages, timeout)`: the reply as `(tag, text)` pieces, `thinking` or `assistant`. Raises
  `ApiError`, with `retryable` and `retry_after`.

## Using it

- **What is sent:** the entries tagged `system`, `user` or `assistant`, with that role. Thinking goes back as the `reasoning_content`
  of the assistant message after it, for the turn in progress only (after the last user message). Cues, errors and anything else are
  left out.
- **What is written:** the reply as an `["assistant"]` message with a `model` field, streamed with `extend`. Reasoning the server
  streams (`reasoning_content`, or `reasoning`) is a `["thinking"]` message the same way; a new message starts each time the text
  turns from one to the other. Then one commit, signed as the model.
- **Handing over:** it claims at `priority` (0) and waits on `outranked_changed()` alongside the server. Outranked, it stops where it
  is, commits what arrived and lets go; outranked before anything arrived, it lets go with nothing written. It writes no note: whoever took the log says why.
- **When it fails:** a connection that fails before any text has arrived is tried again up to `retries` times: unreachable, silent
  for `timeout` seconds, 429, or 5xx. The pause starts at `backoff` seconds and doubles, or is the server's `Retry-After`, never over
  a minute. Meanwhile a `["status"]` message says so, removed before the commit. Anything else, or the last retry failing, is an
  `["error"]` message after what had arrived. That overtakes the cue, so nothing is tried again until there is a new one.

## Why it is this way

- **It answers cues, not the last message.** See [cues.md](../cues.md).
- **The reply is read in a thread, and waited on together with the queue.** `urllib` blocks, so a daemon thread reads the stream and
  hands pieces to the loop. The loop waits for the next piece and for `outranked_changed()` at once, so Ctrl-C stops a reply the
  moment it is asked, even while the server thinks in silence, and a stalled server holds up neither the stop nor the program's exit.
  Checking only when a piece arrived was rejected: a model that thinks for a minute before its first token could not be stopped for
  a minute. Checking on a timer was rejected too: it is late by the period, and reads the queue's folder each time.
- **It finds the system's root certificates itself.** A Python built elsewhere, as uv downloads it, looks for them only where its
  builder's system keeps them; on NixOS that is nowhere, and every HTTPS server fails to verify. So if the default context trusts no
  root, it loads the first CA bundle that exists of those Go looks for (`BUNDLES`), after `$NIX_SSL_CERT_FILE`. `$SSL_CERT_FILE`
  still wins. Adding a dependency (`certifi`) for it was rejected: the system's bundle is the one the user maintains.
- **A certificate failure is not retried.** Asking again gets the same certificate, so it is an error at once, which says to set
  `$SSL_CERT_FILE` if the system does trust it.
- **Text that arrived is never retried.** Starting over would write the answer twice.
- **A status is removed, not committed.** Waiting to reconnect is not part of the conversation; viewers show it live, and history
  stays clean.
- **Errors are messages.** The log is the one place everything shows, so a failure appears next to what caused it.
- **Standard library only.** One POST and a stream of `data:` lines need nothing more.
