<p align="center">
  <img src="docs/banner.svg" alt="gmi: the community command line for GMI Cloud" width="100%">
</p>

<p align="center">
  <a href="LICENSE"><img alt="License: Apache 2.0" src="https://img.shields.io/badge/license-Apache--2.0-0F9D58?labelColor=0B0E11"></a>
  <img alt="Python 3.10 or newer" src="https://img.shields.io/badge/python-3.10%2B-3776AB?labelColor=0B0E11">
  <img alt="Works with any model GMI Cloud serves" src="https://img.shields.io/badge/models-any%20GMI%20Cloud%20model-1FA97A?labelColor=0B0E11">
  <img alt="Built by Codex running GPT-6.1 Sol on GMI Cloud" src="https://img.shields.io/badge/built%20by-Codex%20%2B%20GPT--6.1%20Sol-0F9D58?labelColor=0B0E11">
  <img alt="Community built, not an official GMI Cloud product" src="https://img.shields.io/badge/community%20built-not%20official-8B97A6?labelColor=0B0E11">
</p>

<p align="center">
  <b>Chat with any model on <a href="https://www.gmicloud.ai">GMI Cloud</a> from your terminal.</b><br>
  Switch models mid-conversation, see what everything costs and script it all with JSON.
</p>

<p align="center">
  <a href="#install">Install</a> |
  <a href="#quick-start">Quick start</a> |
  <a href="#the-interactive-session">The session</a> |
  <a href="#scripting-and-automation">Scripting</a> |
  <a href="#models">Models</a> |
  <a href="#configuration-and-privacy">Config</a> |
  <a href="#roadmap">Roadmap</a> |
  <a href="#how-its-built">How it's built</a>
</p>

<p align="center">
  <img src="docs/demo.gif" alt="A recorded gmi session: type slash to see every command, open the model picker, ask a question and watch the formatted answer stream in" width="860">
</p>
<p align="center"><sub>A real session against the live API. GPT-6.1 Sol spent about 18 seconds reasoning before it answered; the recording skips most of that wait.</sub></p>

---

## Why gmi

GMI Cloud has an OpenAI-compatible API, a Model Hub and a web console. `gmi` adds a command line to that.

- **A real session, not a one-shot.** Run `gmi` and you stay in a conversation, steered by slash commands like `/model`, in the style of the modern coding agents.
- **Any model GMI serves.** The list comes live from the API, so new models appear without an update. Switch with `/model` and the conversation carries over.
- **Prices in front of you.** Every model shows its context size and USD price per million tokens, straight from the API record.
- **Built for scripts too.** `gmi chat "..." --json`, piped input, clean exit codes, nothing interactive when you ask it not to be.
- **Careful with your key.** Hidden prompt, verified before it is saved, stored with mode 600, never printed.

> [!NOTE]
> **Status: Day 1 of a six-day public build (20 to 25 Oct 2026).** What is in this README works today and was run against the live API. What is not built yet is listed in the [roadmap](#roadmap) and is not described anywhere else in this file.

## Install

Requires Python 3.10 or newer.

```sh
pip install git+https://github.com/zkasuran/gmi
```

Prefer an isolated tool install? Either of these puts `gmi` on your path:

```sh
pipx install git+https://github.com/zkasuran/gmi
uv tool install git+https://github.com/zkasuran/gmi
```

Update later with `pip install --upgrade git+https://github.com/zkasuran/gmi`. You also need an API key: create one in the [GMI Cloud console](https://console.gmicloud.ai) under API Keys (see the [quickstart](https://docs.gmicloud.ai/quickstart)).

## Quick start

```sh
gmi
```

That opens the session. If you are not logged in yet, the banner says so; type `/login`, paste your key (the input is hidden). gmi checks it against the API before saving it. From a plain shell the same thing is:

```sh
gmi auth login          # hidden prompt, verified, saved to ~/.config/gmi/config.toml
gmi auth status         # API reachable. Active key: gmi_...wxyz
```

Already have the key in your environment? Skip login: `export GMI_API_KEY=...` and run `gmi`.

## The interactive session

Type `/` and a menu lists every command. Tab completes. Replies stream in as formatted Markdown with highlighted code blocks. Every reply ends with a dim status line: the model, the token counts the API reported and the time it took.

<p align="center">
  <img src="docs/slash-menu.png" alt="The gmi banner and the slash command menu listing help, model, models, system, clear, save, load, usage, login and exit" width="760"><br>
  <sub>Type <code>/</code> and every command is listed, with a description.</sub>
</p>

<p align="center">
  <img src="docs/model-picker.png" alt="The model picker filtered by 6.1 showing openai/gpt-6.1-sol with its context size and price" width="760"><br>
  <sub><code>/model</code> opens the picker. Type to filter; context size and price are right there.</sub>
</p>

<p align="center">
  <img src="docs/answer.png" alt="A streamed answer with highlighted inline terms, a code block and the status line showing model, tokens in and out plus elapsed time" width="760"><br>
  <sub>Answers render as Markdown. The dim line under each one shows the model, the API's token counts and the time.</sub>
</p>

### Slash commands

| Command | What it does |
|---|---|
| `/help` | List the commands. |
| `/model` | Open a searchable picker over the live model list. `/model <id>` switches directly. An unknown id is rejected with a "did you mean" hint while your current model stays active. The conversation is kept across switches. |
| `/models` | Table of models with context size and price per 1M tokens. Add filter text to narrow it: `/models sol`. |
| `/system` | Show the system prompt. `/system <text>` sets it and `/system clear` removes it. |
| `/clear` | Start a new conversation. |
| `/save` | Save the conversation to `~/.config/gmi/sessions/<name>.json`. `/save <name>` picks the name, otherwise it is a timestamp. Asks before replacing a saved session. |
| `/load` | `/load <name>` loads a saved conversation. With no name it lists them so you can pick one. |
| `/usage` | Token totals for this session, as reported by the API. |
| `/login` | Verify and save an API key with hidden input. |
| `/exit` | Quit. `Ctrl+D` works too. |

A mistyped command helps you out: `/modle` answers "Unknown command /modle. Did you mean /model?".

### Keys

| Key | Action |
|---|---|
| `Enter` | Send the message. |
| `Alt+Enter` | New line. Also `Shift+Enter` in terminals that report it. Ending a line with `\` then `Enter` works anywhere. |
| `Ctrl+C` | Stop the reply in progress. Text that already arrived stays on screen, but that turn is not added to the conversation, so just ask again. |
| `Ctrl+D` | Quit. |
| `Up`/`Down` | Input history, kept in `~/.config/gmi/history` (mode 600). |
| `Tab` | Complete a slash command. |

In the model picker: type to filter (case-insensitive substring, best match first), arrows to move, `Enter` to pick, `Esc` to cancel. The active model is marked with `*`.

## Scripting and automation

Everything below runs without a session. Add `--json` to any command for machine-readable output with no prompts. Expect a non-zero exit code plus a one-line message on stderr when something fails.

```sh
# Pipe anything in; it is appended to your prompt
gmi chat "Turn these notes into a short checklist" < notes.txt
# - [ ] Review docs
# - [ ] Tag `v1.0` on Sunday
# - [ ] Release on Tuesday

# A commit message from a diff
git diff --staged \
  | gmi chat "Write a commit message for this diff" \
      --system "Reply with one line only."
# Update greeting to say "hello, world"

# The full API response, for jq
gmi chat "Name three HTTP status codes, comma separated, nothing else" --json \
  | jq -r '.choices[0].message.content, .usage.total_tokens'
# 200, 404, 500
# 40

# Find the cheap models: prompt price under $0.30 per million tokens
gmi models --json | jq -r '.data[] | select((.pricing.prompt|tonumber) < 0.0000003) | .id'
```

`gmi chat` with no prompt on a terminal opens the session. With no terminal and no prompt it tells you so instead of hanging.

<details>
<summary><b>Command reference</b></summary>

<br>

**`gmi chat [PROMPT]`**: send a prompt, with standard input appended when piped.

| Option | Meaning |
|---|---|
| `--model TEXT` | Model id. Default: `openai/gpt-6.1-sol`, or `GMI_MODEL`, or your saved default. |
| `--system TEXT` | System instruction. |
| `--max-tokens N` | Maximum output tokens. |
| `--no-stream` | Wait for the complete response instead of streaming. |
| `--no-wrap` | Do not wrap streamed output to the terminal width. |
| `--no-retry` | Do not retry HTTP 429 responses. |
| `--json` | Print the full API response as JSON. |
| `--api-key TEXT` | Use this key (prefer `GMI_API_KEY`, which stays out of shell history). |

**`gmi models`**: list models with context length and USD price per million tokens. `--search TEXT` filters ids and names, `--json` prints the raw records. The current default is marked with `*`.

**`gmi auth`**
- `gmi auth login` verifies a key before saving it. `--stdin` reads it from a pipe: `printf %s "$KEY" | gmi auth login --stdin`.
- `gmi auth status` shows the masked key and checks that the API is reachable.
- `gmi auth logout` removes the saved key. `--yes` skips the confirmation. A key in `GMI_API_KEY` stays active.

**`gmi config get|set default_model [VALUE]`**: read or save the default chat model.

**Global options** (before any command): `--version`, `--api-key TEXT`, `--json`, `--help`.

</details>

## Models

`gmi` reads the model list live from GMI (`GET /v1/models`), so it is never out of date. A session fetches it once and reuses it. At the time of writing that is 82 models, all with prices.

The model for a request is chosen in this order, first match wins:

1. `--model` (or `/model` inside a session)
2. the `GMI_MODEL` environment variable
3. your saved default: `gmi config set default_model <id>`
4. the built-in default, **`openai/gpt-6.1-sol`**

```sh
gmi models --search sol
#   ID                  CONTEXT    PROMPT $/1M  COMPLETION $/1M
#   openai/gpt-5.6-sol  1,050,000  5.00         30.00
# * openai/gpt-6.1-sol  1,050,000  2.00         10.00
#   openai/gpt-6-sol    1,050,000  2.00         10.00
```

Today `gmi` talks to the text models. Image, video and audio models are on the [roadmap](#roadmap).

## Configuration and privacy

| Path | Contents |
|---|---|
| `~/.config/gmi/config.toml` | Your saved API key and default model. Mode 600. |
| `~/.config/gmi/history` | Session input history. Mode 600. |
| `~/.config/gmi/sessions/*.json` | Conversations saved with `/save`. |

| Variable | Meaning |
|---|---|
| `GMI_API_KEY` | API key. Overrides the saved one. |
| `GMI_MODEL` | Default model for this shell. |

The key is resolved as `--api-key`, then `GMI_API_KEY`, then the saved config.

- **Your key is never printed.** Anywhere it appears it is masked to `gmi_...` plus four characters.
- **Login is checked first.** A key the API rejects is never saved, so an existing saved key is not overwritten by a bad one.
- **One destination.** gmi talks to `api.gmi-serving.com` and nowhere else. There is no telemetry, analytics or update check in the code.
- **Sessions are plain JSON** on your disk. Delete them whenever you like.

<details>
<summary><b>Troubleshooting</b></summary>

<br>

| You see | What it means |
|---|---|
| `not logged in, run /login` (banner) | No key found. Run `/login`, `gmi auth login`, or set `GMI_API_KEY`. |
| `API key rejected (401)` | The key is wrong or revoked. Run `gmi auth login` with a valid one. |
| `Model <id> is overloaded on GMI right now. Wait a minute and retry.` | GMI answered 429 "overloaded". gmi already waited as GMI asked (its `Retry-After`, at most 30 seconds, up to twice). Retry shortly, or pass `--no-retry` in scripts. |
| `Rate limit reached (429)` | You hit a quota. Wait, or check your account limits. |
| `Model <id> was not found on GMI.` | Check the id with `gmi models --search <text>`. |
| A long pause after you send a message | Reasoning models can think for a while before the first visible word. The spinner says "Waiting for reply". `Ctrl+C` stops it. |
| `Interactive sessions require a terminal` | You ran `gmi` with no terminal attached. Give it a prompt or use `--json`. |

Platforms: developed and tested on Linux. macOS and Windows have not been tested.

</details>

## Roadmap

Built in public, one working piece a day. The rule: nothing gets announced until it runs.

| Day | Date | What | Status |
|---|---|---|---|
| 1 | Tue 20 Oct | The interactive session, `gmi models`, `gmi chat`, login and config | **Shipped** |
| 2 | Wed 21 Oct | `/image`, `/video` and `/audio` in the session, plus scriptable commands | Planned |
| 3 | Thu 22 Oct | Commands generated from GMI's four published OpenAPI specs | Planned |
| 4 | Fri 23 Oct | `gmi sandbox` (AgentBox), then `gmi` itself on the AgentBox marketplace | Planned |
| 5 | Sat 24 Oct | `gmi mcp serve`: every operation as an MCP tool for your agents | Planned |
| 6 | Sun 25 Oct | v1.0: docs, install one-liner, good first issues | Planned |

Some of the GMI APIs need a different kind of API key than the inference key gmi uses today. Where that limits what can be verified, the day's write-up will say so rather than claim more.

## How it's built

Every line of code in this repository is written by [Codex CLI](https://github.com/openai/codex) running **`openai/gpt-6.1-sol` on GMI Cloud**, the same API gmi talks to. [`AGENTS.md`](AGENTS.md) is the contract it works from: the schedule, the verified API facts and the rules. Changes are run against the live API before they ship. The tests drive the real interactive app through a pseudo-terminal.

## Development

```sh
git clone https://github.com/zkasuran/gmi && cd gmi
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[test]"

pytest -m "not live"      # offline unit tests, no key needed
GMI_API_KEY=... pytest    # everything, including live tests against the real API
```

Live tests make tiny real requests (a few tokens each) and drive the interactive app with `pexpect` and `pyte`.

```
src/gmi/
  cli.py           command line entry point and the scripting commands
  api.py           HTTP client: streaming, retries, error mapping
  config.py        key, model and config file handling
  app/
    session.py     the interactive loop, banner and key bindings
    commands.py    the slash command registry (new commands plug in here)
    picker.py      the searchable model picker
    renderer.py    Markdown rendering and the status line
    state.py       conversation state, usage totals, save and load
tests/             unit tests and live tests
docs/              images used by this README
```

Issues and pull requests are welcome.

## License

[Apache-2.0](LICENSE). `gmi` is a community project. It is not affiliated with or endorsed by GMI Cloud. GMI Cloud is a trademark of its owner.

Built by [@zkasuran](https://x.com/zkasuran) during the [@GMI_Cloud](https://x.com/GMI_Cloud) takeover, 20 to 25 October 2026.
