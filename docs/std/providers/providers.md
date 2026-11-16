# `std/providers/`: the programs that answer a log

A provider claims the log when a cue asks it to ([cues.md](../cues.md)), reads the conversation, and writes a model's reply back as
messages.

| File | What it defines |
|---|---|
| [openai.py](openai.md) | `OpenAI`, `llvim-openai`: any OpenAI-compatible chat API: OpenAI, Ollama, vLLM, llama.cpp, ... |
| [openai_settings.py](openai_settings.md) | Where its key, base URL and model come from |

## Why

- **Every provider does the same few things.** Wait for a cue on its channel; claim the log and check the cue again; stream the reply
  with `append` and `extend`, so viewers see it live; check `outranked()` and stop where it is when it is; commit what it wrote, and
  write a failure as a message.
- **Which model, what tags, how to retry are each provider's.** So a new provider needs core and [conversation.md](../conversation.md)
  and nothing else.
