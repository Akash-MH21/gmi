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
   (63 paths, 93 operations: IAM 30, Cluster Engine 41, Sandbox 21, IDC 1).
   These counts change when GMI updates the specs, so recount before quoting them.
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

## Media API facts (verified live 2026-10-18)

- Base: `https://console.gmicloud.ai/api/v1/ie/requestqueue/apikey`, same `Authorization: Bearer <API key>`,
  same User-Agent rule as inference.
- `GET /models` returns `{"model_ids": [...]}` and includes internal and test entries. Filter on
  `status == "active"` and visible `model_metadata.visibility`, and never show the raw list.
- `GET /models/{id}` returns the real record: `model`, `display_name`, `brief_description`,
  `model_type` (`image`, `video`, `audio`, `language`, ...), `status` (`active` or `inactive`),
  `model_metadata.visibility`, `modalities.input` / `modalities.output` (lists of `{type, required}`),
  `price_info` `{pricing_type, price, unit}` where **`price` is in millionths of a USD** (seedream-5.0-pro
  85000 per image = $0.085, minimax-tts-speech-2.8-turbo 60000 per 1k characters = $0.06,
  kling-3.0-turbo-t2v 112000 per second = $0.112/s), and `parameters` (each with name, type, required,
  plus enum options) that describe the request payload.
- A model is usable when `status == "active"`, visibility is not hidden, and its output modality matches.
- `POST /requests` with `{"model": id, "payload": {...}}` returns `request_id` and `status` (`dispatched`).
  `GET /requests/{id}` gives `status` (dispatched, processing, success, failed, ...) and, on success,
  `outcome` with artifact URLs (for example `video_url`, `thumbnail_image_url`; images and audio use
  their own keys, so read whatever URL fields the outcome holds).
- The queue is shared per account: running music and speech at once starves speech.
- The inference key used to build this project has scope `ie_model` and is rejected (HTTP 401
  "Invalid API key") by the Sandbox and Cluster Engine APIs, so those need a different key type.
  Ask GMI before relying on them.

## The interactive app is the product (project owner, 2026-10-18)

Running `gmi` with no arguments opens an interactive session in the terminal, the way Claude Code,
Codex CLI or kiro-cli work: you stay in it, type messages, and steer it with slash commands. The
subcommands (`gmi chat "..."`, `gmi models --json`, ...) stay for scripts and CI, but the session is
what people see first and what the demos show.

## Models (project owner instruction, 18 Oct, replaces the earlier one model rule)

- **Building:** this repo is written by Codex running `openai/gpt-6.1-sol` on GMI Cloud. That is fixed in
  the builder config and is not something the code controls.
- **The product:** `gmi` supports every model GMI Cloud serves through its API: text, image, video, audio
  and anything else in the catalogue. Never hard-code a list of allowed models. Read what is available from
  the API (`GET /v1/models` for text, and the media model listings) and let the user pick any of them.
- The built-in default chat model stays `openai/gpt-6.1-sol`. Media commands have sensible per-type defaults
  that the user can override and save with `gmi config set`.
- Tests: keep live calls tiny and cheap. Chat tests use `openai/gpt-6.1-sol` with `max_tokens` <= 16. Media tests
  make one small generation per type with the cheapest suitable model, and are marked `live_media` so they
  can be skipped.

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
