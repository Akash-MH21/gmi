# gmi

gmi is a community-built command line for GMI Cloud.

It is built in public during the @GMI_Cloud takeover from Tue 20 to Sun 25 Oct
2026, with one working piece delivered each day.

## Install

Requires Python 3.10 or newer.

```sh
pip install git+https://github.com/zkasuran/gmi
gmi auth login
```

## Quick start

```sh
gmi
```

The inline session stays in your terminal scrollback after exit. Use `/login`
to verify and save a key, then type a message. `gmi chat` also opens the session
when run without a prompt. The default model is `openai/gpt-6.1-sol`.

Enter sends. Alt+Enter or Shift+Enter inserts a newline (terminal support for
Shift+Enter varies); a trailing backslash also continues onto another line.
Up and down recall persistent input history. Ctrl+C cancels a reply or clears
input; Ctrl+D or `/exit` quits. Replies render as streaming Markdown, followed
by API token counts and elapsed time. Missing usage is shown as unknown.

Type `/` for command completions and Tab to complete. Use `/model` for a
searchable live model picker, `/model <id>` to switch while keeping messages,
and `/models sol` to filter the models table. `/system <text>` sets instructions,
`/system clear` removes them, and `/clear` starts a new conversation.
`/save [name]` and `/load [name]` use `~/.config/gmi/sessions/`; `/load` without
a name opens a picker. `/usage` shows API token totals for the running session,
including calls before `/clear` or `/load`. `/help` lists all commands.
History is stored in `~/.config/gmi/history`.

Script commands remain available:

```sh
gmi auth login
gmi auth status
gmi auth logout --yes
gmi models
gmi models --search nano
gmi models --json
gmi chat "Say hello"
cat log.txt | gmi chat "Explain this log"
gmi chat "Say hello" --json
gmi config set default_model openai/gpt-6.1-sol
gmi image "a small red kite" --json
gmi audio "ok" --json
gmi media models --type image
GMI_MODEL=openai/gpt-6.1-sol gmi chat "Say hello"
```

Chat streams by default. Use `--no-stream` to wait for a complete response.
The built-in default model is `openai/gpt-6.1-sol`.

## Status this week

- [x] Day 1: `gmi auth login`, `gmi models`, and `gmi chat`
- [x] Interactive chat with `/model`
- [x] Image, video, and audio requests
- [ ] Generated full API coverage from GMI's four OpenAPI specs
- [ ] `gmi sandbox` on AgentBox
- [ ] `gmi mcp serve`
- [ ] AgentBox marketplace
- [ ] v1.0

## Key handling and errors

Keys resolve in this order: the `--api-key` flag, the `GMI_API_KEY` environment
variable, then `~/.config/gmi/config.toml`. The config file is created with mode
600. `gmi auth login` reads a key from a hidden prompt or standard input and
verifies it with the live models endpoint before saving it. Keys are never
printed, logged, or echoed. Output masks keys such as `gmi_...abcd`.

Every command supports `--json` for machine-readable output without prompts.
Errors go to stderr and return a nonzero exit code. Commands that delete
resources or spend more than a normal model call ask for confirmation; pass
`--yes` to skip it.

## Development

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[test]'
source .venv/bin/activate
pytest
```

`pytest -m live` needs `GMI_API_KEY`. It calls the real API with tiny requests,
using at most 16 output tokens. Live tests do not use API mocks.

## License

Apache-2.0. Community-built, not an official GMI Cloud product.
