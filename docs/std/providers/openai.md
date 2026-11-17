# `std/providers/openai.py`: OpenAI, respond, chat, stream

A provider for the chat-completions API that OpenAI, Ollama, vLLM, llama.cpp and others share, with only the standard library.

```
llvim-openai --configure        # save the base URL, key and model once (the key typed hidden)
llvim-openai                    # answer the log "main" of the working folder, until interrupted
llvim-openai alt -p ~/proj -m llama3 --base-url http://localhost:11434/v1
```

- `OpenAI(model=None, base_url=None, log=None, timeout=60, retries=5, priority=0, once=False, tools=(), context=()).run()`: the program.
  `tools` are offered to the model; `llvim-openai` offers bash and terminal unless given `--no-tools`. `context` is a list of
  [context renderers](../context.md), applied to the log before it is sent. The model and URL
  default to the [settings](openai_settings.md), the log to the session's. No model anywhere: it exits saying so.
- `serve(log, model, base_url, api_key, timeout, retries, priority, tools=(), context=())`, async: answers each `GENERATE` cue (`cues.receive`), until
  cancelled.
- `respond(log, model, base_url, api_key=None, timeout=60, priority=0, retries=5, backoff=1, tools=(), context=())`, async: answers if the model is cued now
  (`cues.take`); whether it wrote anything.
- `answer(log, writer, model, base_url, api_key, timeout, retries, backoff, tools=(), context=())`, async: the answer itself, with the log held.
- `chat(entries)`: the chat messages for a log.
- `stream(base_url, api_key, model, messages, timeout, tools=None)`: the reply as `(tag, text, call)` pieces, `thinking`,
  `assistant` or `tool_call`. For a call the text is a piece of its arguments and `call` says which (`index`, `id`, `name`).
  Raises `ApiError`, with `retryable` and `retry_after`.
- `to_openai(tool)`: a [Tool](../tools/registry.md) in the shape of this API's `tools` list.

## Using it

- **What is sent:** the log as the `context` renderers leave it (with `void.CONTEXT`, without voided messages). Of that, the
  entries tagged `system`, `user` or `assistant`, with that role. Thinking goes back as the `reasoning_content`
  of the assistant message after it, for the turn in progress only (after the last user message). Cues, errors and anything else are
  left out. A tool call goes on the assistant message before it as `tool_calls`, followed by one `tool` message per call, holding
  its result wherever that is in the log, or `[no result: ...]` if it has none. A call whose arguments are not JSON is left out,
  with its result if it has one. A call the user made (`/bash`) is a user message
  instead, `I ran this in a terminal: $ <command>` and its output, once it has a result ([calls.md](../tools/calls.md)).
- **What is written:** the reply as an `["assistant"]` message with a `model` field, streamed with `extend`. Reasoning the server
  streams (`reasoning_content`, or `reasoning`) is a `["thinking"]` message the same way; a new message starts each time the text
  turns from one to the other. A tool call the model streams is a `["tool_call", <tool>]` message of its own, with `call_id` and
  `model`, whose text is the arguments. If the reply made calls, a `tools` cue follows it, for the [runner](../tools/runner.md).
  Then one commit, signed as the model.
- **Handing over:** it claims at `priority` (0) and waits on `outranked_changed()` alongside the server. Outranked, it stops where it
  is, commits what arrived and lets go; outranked before anything arrived, it lets go with nothing written. It writes no note: whoever took the log says why.
- **When it fails:** a connection that fails before any text has arrived is tried again up to `retries` times: unreachable, silent
  for `timeout` seconds, 429, or 5xx. The pause starts at `backoff` seconds and doubles, or is the server's `Retry-After`, never over
  a minute. Meanwhile a `["status"]` message says so, removed before the commit. Anything else, or the last retry failing, is an
  `["error"]` message after what had arrived. That overtakes the cue, so nothing is tried again until there is a new one.

## Why it is this way

- **Every call is answered in what is sent.** The API refuses an assistant message whose calls are not each followed by a result.
  A call cut off by a stop, or by a runner that died, has none, so it is sent with a stand-in.
- **A call cut short is not run.** Outranked mid-reply, the provider commits what arrived but does not cue the runner. Arguments
  that stopped halfway are not a call anyone asked for.
- **A call whose arguments do not parse is not sent.** A stop that lands while the arguments stream leaves half of them in the
  log, and they would go back to the server on every later request. A strict server refuses those requests, so the conversation
  would stay broken until the user voids the call. Sending them with the arguments replaced by `{}` was rejected: that is a call
  the model never made. The log keeps the call as it arrived, so what happened is still there to see.
- **A `/bash` call is the user's message.** The model did not make it, and an assistant message with calls it never made would
  confuse it.

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
