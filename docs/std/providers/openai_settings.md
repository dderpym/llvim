# `std/providers/openai_settings.py`: read, save, api_key, base_url, model

Where the OpenAI provider's settings come from: the environment, else `$LLVIM_HOME/openai.toml`, else a default.

```toml
api_key = "sk-..."
base_url = "https://api.openai.com/v1"    # or http://localhost:11434/v1 for Ollama
model = "gpt-4o-mini"
```

- `api_key()`: `$OPENAI_API_KEY`, else the file's, else `None` (nothing is sent).
- `base_url()`: `$OPENAI_BASE_URL`, else the file's, else OpenAI's. `model()`: `$LLVIM_MODEL`, else the file's, else `None`.
- `read()`: the file, or `{}`. Not TOML, a setting it does not know, or a key that other users can read: raises `ValueError` naming the
  file (and the `chmod 600` to fix it).
- `save(settings)`: writes the file, readable only by you from the moment it exists. Empty values are left out.

## Why it is this way

- **The file is the place for a key.** Never the command line, which other users see in `ps`; and better than the environment, which a
  tmux server keeps from when it started, so a later session can see an old key.
- **A key others can read is refused**, as ssh does with a private key.
