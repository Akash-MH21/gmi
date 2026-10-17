# gmi

Community command line for GMI Cloud. Python 3.10 or newer. Licensed Apache-2.0.

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[test]'
source .venv/bin/activate
gmi auth login
gmi auth status
gmi models
gmi models --search nano --json
gmi chat "Say hello"
gmi chat "Say hello" --no-stream
gmi chat "Say hello" --model openai/gpt-6.1-sol --max-tokens 16 --json
gmi chat "Explain this log" < log.txt
gmi auth logout --yes
```

`gmi auth login --stdin` reads a key from a pipe without echoing it. Login
verifies the key with the live models endpoint before saving
`~/.config/gmi/config.toml` with mode 600. Keys resolve in this order:
`--api-key`, `GMI_API_KEY`, saved config. Prefer the environment or hidden login
prompt over putting keys in shell history. Logout removes the saved file only.

Every leaf command accepts `--api-key` and `--json`; both can also appear before
the command. JSON mode never prompts. Use `gmi auth logout --yes --json` to
confirm removal. Errors go to stderr and return a nonzero status.

Chat streams by default. `--no-stream` waits for a complete response. `--json`
disables streaming and prints the full API response. Use `--system` for a system
instruction. The default model is `openai/gpt-6.1-sol`. Piped text is appended
to the prompt with a blank line. Model prices are USD per million tokens;
optional cache pricing and long-context overrides remain available in JSON.

```sh
pytest -m 'not live'
pytest -m live
pytest
```

Live tests run only when `GMI_API_KEY` is set. They call the real API using
`openai/gpt-6.1-sol` and at most 16 output tokens per request. No API mocks.
Interactive conversation, media, generated API commands, sandbox and MCP
commands are planned for later days.
