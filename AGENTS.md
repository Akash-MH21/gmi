# AGENTS.md: building `gmi`, the command line for GMI Cloud

Read this whole file before changing anything. It is the contract for this repo.

## What we are building

`gmi` is a community-built CLI for GMI Cloud, built in public across a six-day
takeover of @GMI_Cloud (Tue 20 Oct to Sun 25 Oct 2026). Every day's posts show
something that already runs, so **"done" means it works against the live API**,
proven by a test that calls the real endpoint. No mocks pretending to be the API.

The full plan, all committed:

1. Inference from the shell: `gmi models`, `gmi run`, `gmi chat`, plus `gmi image`,
   `gmi video`, `gmi audio` through the request queue.
2. Interactive `gmi chat` with slash commands: `/model`, `/models`, `/system`,
   `/clear`, `/save`, `/load`, `/help`, `/exit`.
3. Full API coverage generated from GMI's four published OpenAPI specs
   (63 paths, 95 operations: IAM 30, Cluster Engine 41, Sandbox 23, IDC 1).
4. `gmi sandbox` (GMI calls this AgentBox): create, exec, push/pull files, extend TTL, kill.
5. `gmi mcp serve` (every operation as an MCP tool) and `gmi mcp login` to `mcp.gmicloud.ai/mcp`.
6. Published as an agent on the AgentBox marketplace.

## Schedule (what must work, and by when)

Posts for a day are due ~12 hours before that day starts, so each day's build must
be finished the day before.

| Takeover day | Must work by | Scope |
|---|---|---|
| Day 1, Tue 20 | **Mon 19 Oct, 20:00 IST** | `gmi auth login`, `gmi models`, `gmi chat` (one-shot + streaming), `--json` |
| Day 2, Wed 21 | Tue 20 | interactive chat with slash commands, model search, image / video / audio |
| Day 3, Thu 22 | Wed 21 | command tree generated from the four OpenAPI specs |
| Day 4, Fri 23 | Thu 22 | `gmi sandbox`, then AgentBox publish |
| Day 5, Sat 24 | Fri 23 | `gmi mcp serve`, `gmi mcp login` |
| Day 6, Sun 25 | Sat 24 | v1.0, docs, install one-liner, good first issues |

## Verified facts about the GMI APIs (checked 2026-10-17)

- Inference is OpenAI-compatible. Base URL `https://api.gmi-serving.com/v1`.
  Auth: `Authorization: Bearer <API key>`. Chat: `POST /v1/chat/completions`
  (supports `stream: true`). Responses API: `POST /v1/responses`.
- `GET /v1/models` **requires** auth (401 without a key). It returns 82 models.
  Each record carries `id` (e.g. `openai/gpt-6.1-sol`, always with a provider prefix),
  `name`, `context_length`, `quantization`, `owned_by` and `pricing`
  (`prompt` and `completion` are USD per token as strings, plus optional
  `input_cache_read`, `input_cache_write` and `overrides` for long prompts).
- **Cloudflare blocks the default Python urllib User-Agent** with HTTP 403
  `error code: 1010`. Always send an explicit User-Agent such as `gmi-cli/<version>`.
- Media (image, video, audio) goes through an async request queue:
  `POST https://console.gmicloud.ai/api/v1/ie/requestqueue/apikey/requests`, then poll
  `.../requests/{id}`. The queue is shared per account: music starves TTS if both run at once.
- OpenAPI specs: `https://docs.gmicloud.ai/api-spec/{ias-public-api,ids-public-api,sandbox_api,service_api}.yaml`.
  IAM, IDC and Cluster Engine use `https://console.gmicloud.ai/api/v1` or `/api`. Sandbox uses `/api/v2` plus
  a per-sandbox `X-Access-Token` for its data plane. The Cluster Engine spec declares session-token auth only.
  Whether an API key works there is still an open question with GMI.

## The one model rule (operator instruction, strict)

**`openai/gpt-6.1-sol` is the only model this project uses.** It is the CLI's built-in default, the model
every live test calls, and the only model any example, README or help text names. Do not call any
other model, not even to probe or test, and never fall back to one automatically. Overload advice says
to wait and retry, not to switch models. Users can still pass any `--model` themselves. That is their choice,
not ours.

## Conventions

- Python 3.10+, packaged with `pyproject.toml`, console script `gmi`. Pin exact dependency versions.
  Keep dependencies few and well-known.
- Every command supports `--json` (machine-readable, no colour, nothing interactive) and returns a non-zero
  exit code on failure. Errors go to stderr with a short, actionable message.
- Key handling. Order: `--api-key` flag, then the `GMI_API_KEY` env var, then the config file at
  `~/.config/gmi/config.toml` (created mode 600). **Never print, log or echo a key.** Mask it in any
  output (`gmi_...abcd`). Never commit one. `gmi auth login` reads the key with a hidden prompt or from stdin,
  and verifies it with `GET /v1/models` before saving.
- Anything that deletes resources or spends money beyond a normal model call asks for confirmation.
  `--yes` skips the prompt.
- Tests: `pytest`. Unit tests for parsing and formatting. **Live tests** marked `@pytest.mark.live`, which run
  only when `GMI_API_KEY` is set, call the real API and keep spend tiny (`max_tokens` <= 16).
- Style: plain, specific English in help text and docs. No em or en dashes anywhere.
- Licence Apache-2.0. Git author `zkasuran <289388318+zkasuran@users.noreply.github.com>`.

## How to report back

End every run with: what now works (exact commands), the test command and its result,
anything unverified, and the next step. Do not claim something works unless you ran it.
